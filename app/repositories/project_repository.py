import uuid

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.sql import ColumnElement

from app.models.group import GroupMembership
from app.models.project import Project
from app.models.task import Task
from app.repositories.base import BaseRepository


def _accessible_condition(user_id: uuid.UUID) -> ColumnElement[bool]:
    """WHERE condition (AD-018) for "can this user access this project":
    direct ownership OR the project is linked to a group (`group_id` set)
    the user is a member of. Used by both `get_accessible_for_user` and
    `list_accessible_for_user` so the two stay in sync.
    """
    member_of_project_group = exists(
        select(GroupMembership.id).where(
            GroupMembership.group_id == Project.group_id,
            GroupMembership.user_id == user_id,
        )
    )
    return or_(
        Project.user_id == user_id,
        and_(Project.group_id.isnot(None), member_of_project_group),
    )


class ProjectRepository(BaseRepository[Project]):
    """Data access for Project. The only layer that talks SQLAlchemy for projects."""

    model = Project

    async def create(self, user_id: uuid.UUID, name: str) -> Project:
        project = Project(user_id=user_id, name=name)
        self._session.add(project)
        await self._session.flush()
        return project

    async def list_accessible_for_user(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Project], int]:
        """Paginated listing (AD-021): returns the requested page alongside
        the total matching count (ignoring `limit`/`offset`), so callers can
        build a `Page[ProjectOut]` envelope. Ordered by `created_at` (with
        `id` as a tiebreaker) so the page boundaries are stable across calls.

        AD-018: includes projects the user directly owns OR that are linked
        to a group the user is a member of. For a user with zero groups
        this reduces to the exact same result set as the old strict
        `list_for_user` (now `get_for_user`'s sibling below) — the
        pagination logic itself is unchanged from before this rename.
        """
        condition = _accessible_condition(user_id)

        count_result = await self._session.execute(
            select(func.count()).select_from(Project).where(condition)
        )
        total = count_result.scalar_one()

        result = await self._session.execute(
            select(Project)
            .where(condition)
            .order_by(Project.created_at, Project.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def get_accessible_for_user(
        self, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> Project | None:
        """AD-018: direct owner OR member of the project's group. Used for
        read/task/attachment access; `get_for_user` below stays strict
        owner-only for rename/delete.
        """
        result = await self._session.execute(
            select(Project).where(Project.id == project_id, _accessible_condition(user_id))
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def set_group(self, project_id: uuid.UUID, group_id: uuid.UUID | None) -> Project:
        """Bare 1-column update of `group_id` — used by GroupService for
        both link (sets the group's id) and unlink (sets None). No business
        logic here; ownership/link-state checks belong to the caller.
        """
        await self._session.execute(
            update(Project).where(Project.id == project_id).values(group_id=group_id)
        )
        await self._session.flush()
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one()

    async def rename(self, project_id: uuid.UUID, name: str) -> Project:
        await self._session.execute(
            update(Project).where(Project.id == project_id).values(name=name)
        )
        await self._session.flush()
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one()

    async def count_tasks(self, project_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Task).where(Task.project_id == project_id)
        )
        return result.scalar_one()
