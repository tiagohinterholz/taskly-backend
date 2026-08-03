import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group, GroupInvite, GroupMembership, GroupRole
from app.models.project import Project
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


def _make_project(
    user_id: uuid.UUID, group_id: uuid.UUID | None = None, name: str = "My Project"
) -> Project:
    return Project(
        id=uuid.uuid4(),
        user_id=user_id,
        group_id=group_id,
        name=name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_invite(
    group_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    consumed_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> GroupInvite:
    return GroupInvite(
        id=uuid.uuid4(),
        group_id=group_id,
        created_by_user_id=created_by_user_id or uuid.uuid4(),
        token_hash="irrelevant-for-tests",
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(days=7)),
        consumed_at=consumed_at,
        revoked_at=revoked_at,
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


class TestCreateInvite:
    async def test_create_invite_by_owner_returns_invite_and_plaintext_token_and_commits(
        self,
    ) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        created_invite = _make_invite(group_id, created_by_user_id=owner_id)
        group_invite_repository.create.return_value = created_invite

        invite, plain_token = await service.create_invite(owner_id, group_id)

        assert invite is created_invite
        assert isinstance(plain_token, str) and len(plain_token) > 0
        # GRP-02: the hash persisted must never equal the plain token returned
        create_call = group_invite_repository.create.call_args
        assert create_call.args[0] == group_id
        assert create_call.args[1] == owner_id
        assert create_call.args[2] != plain_token
        session.commit.assert_awaited_once()

    async def test_create_invite_expires_in_seven_days(self) -> None:
        service, group_repository, group_invite_repository, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_invite_repository.create.return_value = _make_invite(group_id)

        before = datetime.now(timezone.utc)
        await service.create_invite(owner_id, group_id)
        after = datetime.now(timezone.utc)

        expires_at = group_invite_repository.create.call_args.args[3]
        assert before + timedelta(days=7) <= expires_at <= after + timedelta(days=7)

    async def test_create_invite_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.create_invite(member_id, group_id)

        group_invite_repository.create.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_eleventh_invite_within_window_is_rate_limited(self) -> None:
        service, group_repository, group_invite_repository, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_invite_repository.create.return_value = _make_invite(group_id)

        for _ in range(10):
            await service.create_invite(owner_id, group_id)

        # GRP-02 edge case: the 11th invite in the rolling 1h window is blocked
        with pytest.raises(InviteRateLimitExceededError):
            await service.create_invite(owner_id, group_id)

    async def test_rate_limit_is_scoped_per_group(self) -> None:
        service, group_repository, group_invite_repository, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id_a = uuid.uuid4()
        group_id_b = uuid.uuid4()
        group_repository.get_membership.side_effect = lambda group_id, user_id: _make_membership(
            group_id, user_id, GroupRole.OWNER
        )
        group_invite_repository.create.side_effect = lambda group_id, *a: _make_invite(group_id)

        for _ in range(10):
            await service.create_invite(owner_id, group_id_a)

        # Group B's rate limit is independent of group A's
        invite, _token = await service.create_invite(owner_id, group_id_b)
        assert invite.group_id == group_id_b


class TestAcceptInvite:
    async def test_accept_invite_valid_token_creates_membership_and_marks_consumed(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        invite = _make_invite(group_id)
        group_invite_repository.get_by_hash.return_value = invite
        group_repository.get_membership.return_value = None
        group_repository.get_by_id.return_value = _make_group("Team")

        result = await service.accept_invite(acting_user_id, "plain-token")

        group_repository.add_member.assert_awaited_once_with(
            group_id, acting_user_id, GroupRole.MEMBER
        )
        group_invite_repository.mark_consumed.assert_awaited_once_with(invite.id)
        assert result is group_repository.get_by_id.return_value
        session.commit.assert_awaited_once()

    async def test_accept_invite_already_consumed_raises_already_used_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        invite = _make_invite(group_id, consumed_at=datetime.now(timezone.utc))
        group_invite_repository.get_by_hash.return_value = invite

        with pytest.raises(InviteAlreadyUsedError):
            await service.accept_invite(uuid.uuid4(), "plain-token")

        group_repository.add_member.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_accept_invite_expired_raises_invite_expired_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        invite = _make_invite(
            group_id, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        group_invite_repository.get_by_hash.return_value = invite

        with pytest.raises(InviteExpiredError):
            await service.accept_invite(uuid.uuid4(), "plain-token")

        group_repository.add_member.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_accept_invite_at_exact_expiry_instant_is_still_valid(self) -> None:
        # Pins down the `invite.expires_at < now` boundary at the exact tick:
        # the comparison is strict `<`, so `now == expires_at` does NOT raise
        # InviteExpiredError — the invite is still accepted (expiry is
        # exclusive: only strictly-past-expiry instants are rejected). The
        # service calls `datetime.now(timezone.utc)` directly (not
        # injectable), so we freeze it via patching the module's `datetime`
        # name to guarantee `now` is byte-identical to `expires_at`.
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        boundary = datetime(2026, 1, 1, tzinfo=timezone.utc)
        invite = _make_invite(group_id, expires_at=boundary)
        group_invite_repository.get_by_hash.return_value = invite
        group_repository.get_membership.return_value = None
        group_repository.get_by_id.return_value = _make_group("Team")

        with patch("app.services.group_service.datetime") as mock_datetime:
            mock_datetime.now.return_value = boundary
            result = await service.accept_invite(acting_user_id, "plain-token")

        assert result is group_repository.get_by_id.return_value
        group_repository.add_member.assert_awaited_once_with(
            group_id, acting_user_id, GroupRole.MEMBER
        )
        session.commit.assert_awaited_once()

    async def test_accept_invite_unknown_token_raises_invite_not_found_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_invite_repository.get_by_hash.return_value = None

        with pytest.raises(InviteNotFoundError):
            await service.accept_invite(uuid.uuid4(), "unknown-token")

        group_repository.add_member.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_accept_invite_revoked_token_raises_invite_not_found_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        invite = _make_invite(group_id, revoked_at=datetime.now(timezone.utc))
        group_invite_repository.get_by_hash.return_value = invite

        # GRP-03 AC: revoked and unknown tokens raise the same exception,
        # so a router can't distinguish "revoked" from "never existed"
        with pytest.raises(InviteNotFoundError):
            await service.accept_invite(uuid.uuid4(), "revoked-token")

        group_repository.add_member.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_accept_invite_already_a_member_raises_already_member_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        group_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        invite = _make_invite(group_id)
        group_invite_repository.get_by_hash.return_value = invite
        group_repository.get_membership.return_value = _make_membership(group_id, acting_user_id)

        with pytest.raises(AlreadyMemberError):
            await service.accept_invite(acting_user_id, "plain-token")

        group_repository.add_member.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestRevokeInvite:
    async def test_revoke_invite_by_owner_marks_revoked_and_commits(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        invite = _make_invite(group_id)
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        group_invite_repository.get_by_id.return_value = invite

        await service.revoke_invite(owner_id, group_id, invite.id)

        group_invite_repository.mark_revoked.assert_awaited_once_with(invite.id)
        session.commit.assert_awaited_once()

    async def test_revoke_invite_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, group_invite_repository, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.revoke_invite(member_id, group_id, uuid.uuid4())

        group_invite_repository.mark_revoked.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_revoked_invite_then_fails_accept_with_invite_not_found_error(self) -> None:
        # GRP-10: "revoked token then fails accept" — proven at the
        # accept_invite() level, since revoke_invite()'s only job is to set
        # revoked_at (already asserted above); accept_invite() treats any
        # invite with revoked_at set as not-found (tested in TestAcceptInvite
        # too, repeated here to document the end-to-end edge case by name).
        service, group_repository, group_invite_repository, _, _ = _make_service()
        group_id = uuid.uuid4()
        revoked_invite = _make_invite(group_id, revoked_at=datetime.now(timezone.utc))
        group_invite_repository.get_by_hash.return_value = revoked_invite

        with pytest.raises(InviteNotFoundError):
            await service.accept_invite(uuid.uuid4(), "revoked-token")


class TestListPendingInvites:
    async def test_list_pending_invites_by_owner_returns_items_and_total(self) -> None:
        service, group_repository, group_invite_repository, _, _ = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        invite = _make_invite(group_id)
        group_invite_repository.list_pending.return_value = ([invite], 1)

        items, total = await service.list_pending_invites(owner_id, group_id, limit=50, offset=0)

        assert items == [invite]
        assert total == 1
        group_invite_repository.list_pending.assert_awaited_once_with(group_id, 50, 0)

    async def test_list_pending_invites_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, group_invite_repository, _, _ = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.list_pending_invites(member_id, group_id, limit=50, offset=0)

        group_invite_repository.list_pending.assert_not_awaited()


class TestRemoveMember:
    async def test_remove_member_by_owner_removes_membership_and_commits(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        target_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )

        await service.remove_member(owner_id, group_id, target_id)

        group_repository.remove_member.assert_awaited_once_with(group_id, target_id)
        session.commit.assert_awaited_once()

    async def test_remove_member_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.remove_member(member_id, group_id, uuid.uuid4())

        group_repository.remove_member.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestLeave:
    async def test_leave_as_sole_owner_raises_sole_owner_cannot_leave_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )

        with pytest.raises(SoleOwnerCannotLeaveError):
            await service.leave(owner_id, group_id)

        group_repository.remove_member.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_leave_as_member_succeeds_and_commits(self) -> None:
        service, group_repository, _, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        await service.leave(member_id, group_id)

        group_repository.remove_member.assert_awaited_once_with(group_id, member_id)
        session.commit.assert_awaited_once()

    async def test_leave_when_not_a_member_raises_group_not_found_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        group_repository.get_membership.return_value = None

        with pytest.raises(GroupNotFoundError):
            await service.leave(uuid.uuid4(), uuid.uuid4())

        group_repository.remove_member.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestTransferOwnership:
    async def test_transfer_ownership_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.transfer_ownership(member_id, group_id, uuid.uuid4())

        group_repository.set_role.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_transfer_ownership_to_non_member_raises_not_group_member_error(self) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        new_owner_id = uuid.uuid4()

        async def get_membership(group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership | None:
            if user_id == owner_id:
                return _make_membership(group_id, owner_id, GroupRole.OWNER)
            return None

        group_repository.get_membership.side_effect = get_membership

        with pytest.raises(NotGroupMemberError):
            await service.transfer_ownership(owner_id, group_id, new_owner_id)

        group_repository.set_role.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_transfer_ownership_happy_path_demotes_old_owner_before_promoting_new_owner(
        self,
    ) -> None:
        service, group_repository, _, _, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        new_owner_id = uuid.uuid4()

        async def get_membership(group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership:
            role = GroupRole.OWNER if user_id == owner_id else GroupRole.MEMBER
            return _make_membership(group_id, user_id, role)

        group_repository.get_membership.side_effect = get_membership

        await service.transfer_ownership(owner_id, group_id, new_owner_id)

        # GRP-09: exactly one owner after the swap — proving the ordering
        # avoids a transient two-OWNER state that the DB's partial unique
        # index would reject (see test_group_repository.py's set_role test,
        # which requires this same demote-then-promote order for real).
        assert group_repository.set_role.await_args_list == [
            call(group_id, owner_id, GroupRole.MEMBER),
            call(group_id, new_owner_id, GroupRole.OWNER),
        ]
        session.commit.assert_awaited_once()


class TestLinkProject:
    async def test_link_project_by_owner_of_group_and_project_sets_group_id(self) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        project_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        project_repository.get_for_user.return_value = _make_project(owner_id, group_id=None)
        linked_project = _make_project(owner_id, group_id=group_id)
        project_repository.set_group.return_value = linked_project

        result = await service.link_project(owner_id, group_id, project_id)

        assert result is linked_project
        assert result.group_id == group_id
        project_repository.get_for_user.assert_awaited_once_with(project_id, owner_id)
        project_repository.set_group.assert_awaited_once_with(project_id, group_id)
        session.commit.assert_awaited_once()

    async def test_link_project_by_non_owner_of_group_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.link_project(member_id, group_id, uuid.uuid4())

        project_repository.get_for_user.assert_not_awaited()
        project_repository.set_group.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_link_project_not_owned_by_acting_user_raises_project_not_found_error(
        self,
    ) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        project_repository.get_for_user.return_value = None

        with pytest.raises(ProjectNotFoundError):
            await service.link_project(owner_id, group_id, uuid.uuid4())

        project_repository.set_group.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_link_project_already_linked_to_another_group_raises_already_linked_error(
        self,
    ) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        other_group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        project_repository.get_for_user.return_value = _make_project(
            owner_id, group_id=other_group_id
        )

        with pytest.raises(ProjectAlreadyLinkedError):
            await service.link_project(owner_id, group_id, uuid.uuid4())

        project_repository.set_group.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestUnlinkProject:
    async def test_unlink_project_by_owner_nulls_group_id(self) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        project_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        project_repository.get_by_id.return_value = _make_project(owner_id, group_id=group_id)
        unlinked_project = _make_project(owner_id, group_id=None)
        project_repository.set_group.return_value = unlinked_project

        result = await service.unlink_project(owner_id, group_id, project_id)

        assert result is unlinked_project
        assert result.group_id is None
        project_repository.set_group.assert_awaited_once_with(project_id, None)
        session.commit.assert_awaited_once()

    async def test_unlink_project_by_non_owner_raises_not_group_owner_error(self) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        member_id = uuid.uuid4()
        group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, member_id, GroupRole.MEMBER
        )

        with pytest.raises(NotGroupOwnerError):
            await service.unlink_project(member_id, group_id, uuid.uuid4())

        project_repository.set_group.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_unlink_project_not_linked_to_this_group_raises_project_not_found_error(
        self,
    ) -> None:
        service, group_repository, _, project_repository, session = _make_service()
        owner_id = uuid.uuid4()
        group_id = uuid.uuid4()
        other_group_id = uuid.uuid4()
        group_repository.get_membership.return_value = _make_membership(
            group_id, owner_id, GroupRole.OWNER
        )
        project_repository.get_by_id.return_value = _make_project(
            owner_id, group_id=other_group_id
        )

        with pytest.raises(ProjectNotFoundError):
            await service.unlink_project(owner_id, group_id, uuid.uuid4())

        project_repository.set_group.assert_not_awaited()
        session.commit.assert_not_awaited()
