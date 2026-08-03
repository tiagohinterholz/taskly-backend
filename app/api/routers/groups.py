import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session
from app.api.pagination import Page, PaginationParams
from app.models.group import Group
from app.models.project import Project
from app.models.user import User
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository
from app.services.group_service import (
    AlreadyMemberError,
    GroupHasProjectsError,
    GroupNotFoundError,
    GroupService,
    InviteAlreadyUsedError,
    InviteExpiredError,
    InviteNotFoundError,
    InviteRateLimitExceededError,
    NotGroupMemberError,
    NotGroupOwnerError,
    ProjectAlreadyLinkedError,
    SoleOwnerCannotLeaveError,
)
from app.services.project_service import ProjectNotFoundError

# No blanket prefix on this router (unlike projects.py's `prefix="/projects"`):
# most routes live under /groups/..., but accepting an invite
# (POST /invites/{token}/accept) deliberately isn't nested under a known
# group_id (design.md — the caller only has a token). Declaring each route's
# full path explicitly lets both shapes coexist on one APIRouter instance.
router = APIRouter(tags=["groups"])


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime


class GroupWithRoleOut(GroupOut):
    """`GET /groups` needs the acting user's own role alongside each group
    (spec P3 AC1) — built manually from GroupRepository.list_for_user's
    `(Group, GroupRole)` tuples rather than `from_attributes`, since a plain
    tuple has no named attributes to read.
    """

    role: str


class MemberOut(BaseModel):
    """Built manually from GroupRepository.list_members's `(GroupMembership,
    email)` tuples rather than `from_attributes`, same reason as
    `GroupWithRoleOut` above — a plain tuple has no named attributes.
    """

    user_id: uuid.UUID
    email: str
    role: str
    created_at: datetime


class GroupInviteOut(BaseModel):
    """Invite metadata only — never the plain token or its hash. Used by
    the listing endpoint (`GET .../invites`), which must not let a caller
    recover a usable token after the fact.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by_user_id: uuid.UUID
    expires_at: datetime
    created_at: datetime


class GroupInviteCreateOut(GroupInviteOut):
    """Returned only by the create-invite endpoint: the one response that
    carries the plain-text token, exactly once, never recoverable again.
    """

    token: str


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: uuid.UUID


class ProjectLinkOut(BaseModel):
    """Minimal confirmation of a link/unlink call: just the fields that
    actually changed, rather than the full ProjectOut shape (which doesn't
    even expose group_id) — reused across both endpoints since both mutate
    the same field.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    group_id: uuid.UUID | None


# GroupService.create_invite() rate-limits per (group_id, owner_user_id) using
# an instance-level dict (see GroupService.__init__). A fresh GroupService is
# built per request (session is request-scoped), so this module-level dict is
# injected into every instance via the factory below — same pattern as
# auth.py's `_shared_failed_attempts` shared across `_get_auth_service` calls,
# so the 10/hour window is actually enforced across separate HTTP requests.
_shared_invite_attempts: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = {}


def _get_group_service(session: AsyncSession = Depends(get_db_session)) -> GroupService:
    return GroupService(
        session=session,
        group_repository=GroupRepository(session),
        group_invite_repository=GroupInviteRepository(session),
        project_repository=ProjectRepository(session),
        invite_rate_limit=_shared_invite_attempts,
    )


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateRequest,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Group:
    return await group_service.create(user.id, payload.name)


@router.get("/groups", response_model=Page[GroupWithRoleOut])
async def list_groups(
    pagination: PaginationParams = Depends(),
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Page[GroupWithRoleOut]:
    groups_with_roles, total = await group_service.list_for_user(
        user.id, pagination.limit, pagination.offset
    )
    items = [
        GroupWithRoleOut(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            updated_at=group.updated_at,
            role=role.value,
        )
        for group, role in groups_with_roles
    ]
    return Page[GroupWithRoleOut](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def rename_group(
    group_id: uuid.UUID,
    payload: GroupRenameRequest,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Group:
    try:
        return await group_service.rename(user.id, group_id, payload.name)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> None:
    try:
        await group_service.delete(user.id, group_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except GroupHasProjectsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="unlink all projects before deleting the group",
        ) from exc


@router.get("/groups/{group_id}/members", response_model=Page[MemberOut])
async def list_group_members(
    group_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Page[MemberOut]:
    try:
        members_with_email, total = await group_service.list_members(
            user.id, group_id, pagination.limit, pagination.offset
        )
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    items = [
        MemberOut(user_id=member.user_id, email=email, role=member.role.value, created_at=member.created_at)
        for member, email in members_with_email
    ]
    return Page[MemberOut](items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.post(
    "/groups/{group_id}/invites", response_model=GroupInviteCreateOut, status_code=status.HTTP_201_CREATED
)
async def create_invite(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> GroupInviteCreateOut:
    try:
        invite, plain_token = await group_service.create_invite(user.id, group_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except InviteRateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many invites generated, try again later",
        ) from exc
    return GroupInviteCreateOut(
        id=invite.id,
        created_by_user_id=invite.created_by_user_id,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        token=plain_token,
    )


@router.get("/groups/{group_id}/invites", response_model=Page[GroupInviteOut])
async def list_group_invites(
    group_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Page[GroupInviteOut]:
    try:
        invites, total = await group_service.list_pending_invites(
            user.id, group_id, pagination.limit, pagination.offset
        )
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    return Page[GroupInviteOut](
        items=invites, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.delete("/groups/{group_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    group_id: uuid.UUID,
    invite_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> None:
    try:
        await group_service.revoke_invite(user.id, group_id, invite_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found") from exc


@router.post("/invites/{token}/accept", response_model=GroupOut)
async def accept_invite(
    token: str,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Group:
    try:
        return await group_service.accept_invite(user.id, token)
    except InviteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found") from exc
    except InviteExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="invite expired") from exc
    except InviteAlreadyUsedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invite already used") from exc
    except AlreadyMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="you are already a member of this group"
        ) from exc


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> None:
    try:
        await group_service.remove_member(user.id, group_id, user_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc


@router.post("/groups/{group_id}/leave")
async def leave_group(
    group_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> dict[str, str]:
    try:
        await group_service.leave(user.id, group_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except SoleOwnerCannotLeaveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="transfer ownership before leaving the group",
        ) from exc
    return {"message": "left group"}


@router.post("/groups/{group_id}/transfer-ownership")
async def transfer_ownership(
    group_id: uuid.UUID,
    payload: TransferOwnershipRequest,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> dict[str, str]:
    try:
        await group_service.transfer_ownership(user.id, group_id, payload.new_owner_user_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except NotGroupMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user is not a member of this group"
        ) from exc
    return {"message": "ownership transferred"}


@router.post("/groups/{group_id}/projects/{project_id}/link", response_model=ProjectLinkOut)
async def link_project(
    group_id: uuid.UUID,
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Project:
    try:
        return await group_service.link_project(user.id, group_id, project_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found") from exc
    except ProjectAlreadyLinkedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="project already linked to another group"
        ) from exc


@router.post("/groups/{group_id}/projects/{project_id}/unlink", response_model=ProjectLinkOut)
async def unlink_project(
    group_id: uuid.UUID,
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    group_service: GroupService = Depends(_get_group_service),
) -> Project:
    try:
        return await group_service.unlink_project(user.id, group_id, project_id)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    except NotGroupOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="only the group owner can perform this action"
        ) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="project not linked to this group"
        ) from exc
