import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db_session
from app.api.pagination import Page, PaginationParams
from app.models.group import Group
from app.models.user import User
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository
from app.services.group_service import (
    GroupHasProjectsError,
    GroupNotFoundError,
    GroupService,
    NotGroupOwnerError,
)

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
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    role: str
    created_at: datetime


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
        members, total = await group_service.list_members(
            user.id, group_id, pagination.limit, pagination.offset
        )
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found") from exc
    return Page[MemberOut](items=members, total=total, limit=pagination.limit, offset=pagination.offset)
