import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update

from app.models.group import Group, GroupMembership, GroupRole
from app.models.project import Project
from app.models.user import User
from app.repositories.base import BaseRepository


class GroupRepository(BaseRepository[Group]):
    """Data access for Group/GroupMembership. The only layer that talks
    SQLAlchemy for groups and their memberships.
    """

    model = Group

    async def create(self, name: str, owner_user_id: uuid.UUID) -> Group:
        """Atomically creates the group AND its Owner membership: the
        group's id is generated here (instead of relying on the model's
        default=uuid.uuid4, which SQLAlchemy only evaluates at flush time)
        so both rows can be added and flushed together in a single
        flush() — no intermediate flush needed to learn the group's id.
        """
        group_id = uuid.uuid4()
        group = Group(id=group_id, name=name)
        membership = GroupMembership(group_id=group_id, user_id=owner_user_id, role=GroupRole.OWNER)
        self._session.add(group)
        self._session.add(membership)
        await self._session.flush()
        return group

    async def rename(self, group_id: uuid.UUID, name: str) -> Group:
        await self._session.execute(update(Group).where(Group.id == group_id).values(name=name))
        await self._session.flush()
        result = await self._session.execute(select(Group).where(Group.id == group_id))
        return result.scalar_one()

    async def get_membership(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMembership | None:
        result = await self._session.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_members(
        self, group_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[tuple[GroupMembership, str]], int]:
        """Paginated listing (AD-021): returns the requested page (each row
        paired with that member's email, joined from User — a UUID alone
        isn't a usable identity for a member-list UI) alongside the total
        matching count, ordered by `created_at`/`id` for stable page
        boundaries — same shape as `ProjectRepository.list_for_user`.
        """
        count_result = await self._session.execute(
            select(func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group_id)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(GroupMembership, User.email)
            .join(User, User.id == GroupMembership.user_id)
            .where(GroupMembership.group_id == group_id)
            .order_by(GroupMembership.created_at, GroupMembership.id)
            .limit(limit)
            .offset(offset)
        )
        return [(membership, email) for membership, email in result.all()], total

    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[tuple[Group, GroupRole]], int]:
        """Paginated listing (AD-021) of every group the user belongs to,
        paired with that user's OWN role in each group (never another
        member's role) — a join of GroupMembership -> Group filtered by
        user_id. Ordered by the group's `created_at`/`id`.
        """
        count_result = await self._session.execute(
            select(func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.user_id == user_id)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Group, GroupMembership.role)
            .join(GroupMembership, GroupMembership.group_id == Group.id)
            .where(GroupMembership.user_id == user_id)
            .order_by(Group.created_at, Group.id)
            .limit(limit)
            .offset(offset)
        )
        return [(group, role) for group, role in result.all()], total

    async def add_member(
        self, group_id: uuid.UUID, user_id: uuid.UUID, role: GroupRole
    ) -> GroupMembership:
        membership = GroupMembership(group_id=group_id, user_id=user_id, role=role)
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def remove_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._session.execute(
            sa_delete(GroupMembership).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
            )
        )
        await self._session.flush()

    async def set_role(self, group_id: uuid.UUID, user_id: uuid.UUID, role: GroupRole) -> None:
        """Bare update-by-(group_id, user_id), no business logic. The
        atomicity of swapping two roles (transfer_ownership) — and the
        ordering needed to respect the one-owner-per-group DB constraint —
        is the future GroupService's job (T10), not this method's.
        """
        await self._session.execute(
            update(GroupMembership)
            .where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id)
            .values(role=role)
        )
        await self._session.flush()

    async def count_linked_projects(self, group_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Project).where(Project.group_id == group_id)
        )
        return result.scalar_one()
