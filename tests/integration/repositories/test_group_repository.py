from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import GroupRole
from app.models.project import Project
from app.repositories.group_repository import GroupRepository
from app.repositories.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "owner@example.com"):
    return await UserRepository(db_session).create(email=email, password_hash="hash")


class TestGroupRepositoryCreate:
    async def test_create_persists_group_and_owner_membership_atomically(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "create-owner@example.com")
        repo = GroupRepository(db_session)

        group = await repo.create(name="Team", owner_user_id=owner.id)

        assert group.id is not None
        assert group.name == "Team"
        membership = await repo.get_membership(group.id, owner.id)
        assert membership is not None
        assert membership.role == GroupRole.OWNER


class TestGroupRepositoryGetMembership:
    async def test_get_membership_returns_membership_for_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "gm-owner@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)

        membership = await repo.get_membership(group.id, owner.id)

        assert membership is not None
        assert membership.user_id == owner.id
        assert membership.group_id == group.id

    async def test_get_membership_returns_none_when_not_a_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "gm-owner2@example.com")
        other = await _make_user(db_session, "gm-other2@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)

        membership = await repo.get_membership(group.id, other.id)

        assert membership is None


class TestGroupRepositoryListMembers:
    async def test_list_members_returns_all_members_within_limit(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "lm-owner@example.com")
        member = await _make_user(db_session, "lm-member@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)
        await repo.add_member(group.id, member.id, GroupRole.MEMBER)

        page, total = await repo.list_members(group.id, limit=50, offset=0)

        assert total == 2
        assert {m.user_id for m in page} == {owner.id, member.id}

    async def test_list_members_paginates_with_total_reflecting_full_count(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "lmp-owner@example.com")
        member = await _make_user(db_session, "lmp-member@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)
        await repo.add_member(group.id, member.id, GroupRole.MEMBER)

        page, total = await repo.list_members(group.id, limit=1, offset=0)

        assert total == 2
        assert len(page) == 1


class TestGroupRepositoryListForUser:
    async def test_list_for_user_returns_each_groups_own_role(
        self, db_session: AsyncSession
    ) -> None:
        user_a = await _make_user(db_session, "lfu-a@example.com")
        user_b = await _make_user(db_session, "lfu-b@example.com")
        repo = GroupRepository(db_session)
        group_owned = await repo.create(name="Owned by A", owner_user_id=user_a.id)
        group_joined = await repo.create(name="Owned by B", owner_user_id=user_b.id)
        await repo.add_member(group_joined.id, user_a.id, GroupRole.MEMBER)

        results, total = await repo.list_for_user(user_a.id, limit=50, offset=0)

        assert total == 2
        roles_by_group = {group.id: role for group, role in results}
        assert roles_by_group[group_owned.id] == GroupRole.OWNER
        assert roles_by_group[group_joined.id] == GroupRole.MEMBER

    async def test_list_for_user_paginates_with_total_reflecting_full_count(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, "lfup@example.com")
        repo = GroupRepository(db_session)
        for i in range(3):
            await repo.create(name=f"Group {i}", owner_user_id=user.id)

        page, total = await repo.list_for_user(user.id, limit=2, offset=0)

        assert total == 3
        assert len(page) == 2

    async def test_list_for_user_excludes_groups_user_is_not_a_member_of(
        self, db_session: AsyncSession
    ) -> None:
        user_a = await _make_user(db_session, "lfux-a@example.com")
        user_b = await _make_user(db_session, "lfux-b@example.com")
        repo = GroupRepository(db_session)
        await repo.create(name="A's group", owner_user_id=user_a.id)
        group_b = await repo.create(name="B's group", owner_user_id=user_b.id)

        results, total = await repo.list_for_user(user_b.id, limit=50, offset=0)

        assert total == 1
        assert [group.id for group, _ in results] == [group_b.id]


class TestGroupRepositoryAddRemoveMember:
    async def test_add_member_creates_membership_with_given_role(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "arm-owner@example.com")
        member = await _make_user(db_session, "arm-member@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)

        membership = await repo.add_member(group.id, member.id, GroupRole.MEMBER)

        assert membership.id is not None
        assert membership.group_id == group.id
        assert membership.user_id == member.id
        assert membership.role == GroupRole.MEMBER

    async def test_remove_member_deletes_the_membership(self, db_session: AsyncSession) -> None:
        owner = await _make_user(db_session, "arm2-owner@example.com")
        member = await _make_user(db_session, "arm2-member@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)
        await repo.add_member(group.id, member.id, GroupRole.MEMBER)

        await repo.remove_member(group.id, member.id)

        assert await repo.get_membership(group.id, member.id) is None


class TestGroupRepositorySetRole:
    async def test_set_role_swaps_owner_and_member_for_ownership_transfer(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "sr-owner@example.com")
        member = await _make_user(db_session, "sr-member@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)
        await repo.add_member(group.id, member.id, GroupRole.MEMBER)

        # Demote the current owner first, then promote the member -- the
        # DB's one-owner-per-group partial unique index would reject the
        # reverse order (two OWNER rows existing at once).
        await repo.set_role(group.id, owner.id, GroupRole.MEMBER)
        await repo.set_role(group.id, member.id, GroupRole.OWNER)

        new_owner = await repo.get_membership(group.id, member.id)
        old_owner = await repo.get_membership(group.id, owner.id)
        assert new_owner is not None
        assert new_owner.role == GroupRole.OWNER
        assert old_owner is not None
        assert old_owner.role == GroupRole.MEMBER


class TestGroupRepositoryCountLinkedProjects:
    async def test_count_linked_projects_returns_zero_when_none_linked(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "clp-owner@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)

        count = await repo.count_linked_projects(group.id)

        assert count == 0

    async def test_count_linked_projects_returns_number_of_projects_linked(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, "clp2-owner@example.com")
        repo = GroupRepository(db_session)
        group = await repo.create(name="Team", owner_user_id=owner.id)
        db_session.add(Project(user_id=owner.id, name="P1", group_id=group.id))
        db_session.add(Project(user_id=owner.id, name="P2", group_id=group.id))
        await db_session.flush()

        count = await repo.count_linked_projects(group.id)

        assert count == 2
