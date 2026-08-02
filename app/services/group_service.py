import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group, GroupMembership, GroupRole
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository


class GroupNotFoundError(Exception):
    """Raised when group_id doesn't exist or the acting user isn't a member
    of it — same exception either way so a router can map it to a 404
    without ever revealing whether the group exists (AD-012 pattern).
    """


class NotGroupOwnerError(Exception):
    """Raised when the acting user is a member of the group but not its
    Owner, for an action that requires Owner privileges.
    """


class GroupHasProjectsError(Exception):
    """Raised by delete() when the group still has projects linked to it —
    deletion is blocked until they're unlinked first (GRP-12).
    """


class GroupService:
    """Group business rules: lifecycle (create/rename/delete), listing,
    invites, membership management, and project link/unlink. Repositories
    only flush() (AD-011) — this service owns the transaction boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        group_repository: GroupRepository,
        group_invite_repository: GroupInviteRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self._session = session
        self._group_repository = group_repository
        self._group_invite_repository = group_invite_repository
        self._project_repository = project_repository

    async def create(self, owner_user_id: uuid.UUID, name: str) -> Group:
        group = await self._group_repository.create(name, owner_user_id)
        await self._session.commit()
        return group

    async def rename(self, acting_user_id: uuid.UUID, group_id: uuid.UUID, name: str) -> Group:
        await self._require_owner(acting_user_id, group_id)
        group = await self._group_repository.rename(group_id, name)
        await self._session.commit()
        return group

    async def delete(self, acting_user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        await self._require_owner(acting_user_id, group_id)
        linked_project_count = await self._group_repository.count_linked_projects(group_id)
        if linked_project_count > 0:
            raise GroupHasProjectsError(group_id)
        await self._group_repository.delete(group_id)
        await self._session.commit()

    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[tuple[Group, GroupRole]], int]:
        return await self._group_repository.list_for_user(user_id, limit, offset)

    async def list_members(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[GroupMembership], int]:
        membership = await self._group_repository.get_membership(group_id, acting_user_id)
        if membership is None:
            raise GroupNotFoundError(group_id)
        return await self._group_repository.list_members(group_id, limit, offset)

    async def _require_owner(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID
    ) -> GroupMembership:
        membership = await self._group_repository.get_membership(group_id, acting_user_id)
        if membership is None:
            raise GroupNotFoundError(group_id)
        if membership.role != GroupRole.OWNER:
            raise NotGroupOwnerError(group_id)
        return membership
