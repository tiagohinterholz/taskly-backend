import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group, GroupMembership, GroupRole
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository
from app.services.group_service import (
    GroupHasProjectsError,
    GroupNotFoundError,
    GroupService,
    NotGroupOwnerError,
)


def _make_service() -> tuple[GroupService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    session = AsyncMock(spec=AsyncSession)
    group_repository = AsyncMock(spec=GroupRepository)
    group_invite_repository = AsyncMock(spec=GroupInviteRepository)
    project_repository = AsyncMock(spec=ProjectRepository)
    service = GroupService(
        session=session,
        group_repository=group_repository,
        group_invite_repository=group_invite_repository,
        project_repository=project_repository,
    )
    return service, group_repository, group_invite_repository, project_repository, session


def _make_group(name: str = "Team") -> Group:
    return Group(
        id=uuid.uuid4(),
        name=name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_membership(
    group_id: uuid.UUID, user_id: uuid.UUID, role: GroupRole = GroupRole.MEMBER
) -> GroupMembership:
    return GroupMembership(
        id=uuid.uuid4(),
        group_id=group_id,
        user_id=user_id,
        role=role,
        created_at=datetime.now(timezone.utc),
    )


class TestCreate:
    async def test_create_persists_group_via_repository_and_commits(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        created_group = _make_group("Team")
        group_repository.create.return_value = created_group

        result = await service.create(owner_id, "Team")

        assert result is created_group
        group_repository.create.assert_awaited_once_with("Team", owner_id)
        session.commit.assert_awaited_once()


class TestRename:
    async def test_rename_updates_group_name_when_acting_user_is_owner(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        renamed_group = _make_group("New Name")
        group_repository.rename.return_value = renamed_group

        result = await service.rename(owner_id, group_id, "New Name")

        assert result is renamed_group
        assert result.name == "New Name"
        group_repository.rename.assert_awaited_once_with(group_id, "New Name")
        session.commit.assert_awaited_once()

    async def test_rename_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.rename(member_id, group_id, "New Name")

        group_repository.rename.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_rename_when_acting_user_not_a_member_raises_group_not_found_error(
        self,
    ) -> None:
        service, group_repository, _, _, session = _make_service()
        group_repository.get_membership.return_value = None

        with pytest.raises(GroupNotFoundError):
            await service.rename(uuid.uuid4(), uuid.uuid4(), "New Name")

        group_repository.rename.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestDelete:
    async def test_delete_blocked_when_group_has_linked_projects(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_repository.count_linked_projects.return_value = 2

        with pytest.raises(GroupHasProjectsError):
            await service.delete(owner_id, group_id)

        group_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_delete_succeeds_when_no_linked_projects(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_repository.count_linked_projects.return_value = 0

        await service.delete(owner_id, group_id)

        group_repository.delete.assert_awaited_once_with(group_id)
        session.commit.assert_awaited_once()

    async def test_delete_checks_linked_project_count_before_deleting(self) -> None:
        service, group_repository, _, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_repository.count_linked_projects.return_value = 0

        await service.delete(owner_id, group_id)

        method_names = [call[0] for call in group_repository.mock_calls]
        assert method_names.index("count_linked_projects") < method_names.index("delete")

    async def test_delete_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.delete(member_id, group_id)

        group_repository.count_linked_projects.assert_not_awaited()
        group_repository.delete.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestListForUser:
    async def test_list_for_user_returns_groups_with_roles_and_total(self) -> None:
        service, group_repository, _, _, _ = _make_service()
        user_id = uuid.uuid4()
        group = _make_group("Team")
        group_repository.list_for_user.return_value = ([(group, GroupRole.OWNER)], 1)

        items, total = await service.list_for_user(user_id, limit=50, offset=0)

        assert items == [(group, GroupRole.OWNER)]
        assert total == 1
        group_repository.list_for_user.assert_awaited_once_with(user_id, 50, 0)

    async def test_list_for_user_returns_empty_when_user_has_no_groups(self) -> None:
        service, group_repository, _, _, _ = _make_service()
        group_repository.list_for_user.return_value = ([], 0)

        items, total = await service.list_for_user(uuid.uuid4(), limit=50, offset=0)

        assert items == []
        assert total == 0


class TestListMembers:
    async def test_list_members_returns_members_and_total_for_a_member(self) -> None:
        service, group_repository, _, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        membership = _make_membership(group_id, owner_id, GroupRole.OWNER)
        group_repository.get_membership.return_value = membership
        group_repository.list_members.return_value = ([membership], 1)

        items, total = await service.list_members(owner_id, group_id, limit=50, offset=0)

        assert items == [membership]
        assert total == 1
        group_repository.list_members.assert_awaited_once_with(group_id, 50, 0)

    async def test_list_members_by_non_member_raises_group_not_found_error(self) -> None:
        service, group_repository, _, _, _ = _make_service()
        group_repository.get_membership.return_value = None

        with pytest.raises(GroupNotFoundError):
            await service.list_members(uuid.uuid4(), uuid.uuid4(), limit=50, offset=0)

        group_repository.list_members.assert_not_awaited()
