from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import GroupRole
from app.models.task import Task
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "owner@example.com"):
    return await UserRepository(db_session).create(email=email, password_hash="hash")


class TestProjectRepositoryCreate:
    async def test_create_persists_project_for_user(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)

        project = await repo.create(user_id=user.id, name="Personal")

        assert project.id is not None
        assert project.user_id == user.id
        assert project.name == "Personal"


class TestProjectRepositoryListAccessibleForUser:
    async def test_list_accessible_for_user_returns_only_that_users_projects(
        self, db_session: AsyncSession
    ) -> None:
        user_a = await _make_user(db_session, email="a@example.com")
        user_b = await _make_user(db_session, email="b@example.com")
        repo = ProjectRepository(db_session)
        project_a = await repo.create(user_id=user_a.id, name="A's project")
        await repo.create(user_id=user_b.id, name="B's project")

        projects_for_a, total = await repo.list_accessible_for_user(user_a.id, limit=50, offset=0)

        assert [p.id for p in projects_for_a] == [project_a.id]
        assert all(p.user_id == user_a.id for p in projects_for_a)
        assert total == 1

    async def test_list_accessible_for_user_includes_group_accessible_projects(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="lafu-owner@example.com")
        member = await _make_user(db_session, email="lafu-member@example.com")
        project_repo = ProjectRepository(db_session)
        group_repo = GroupRepository(db_session)
        group = await group_repo.create(name="Team", owner_user_id=owner.id)
        await group_repo.add_member(group.id, member.id, GroupRole.MEMBER)
        own_project = await project_repo.create(user_id=member.id, name="Member's own")
        shared_project = await project_repo.create(user_id=owner.id, name="Shared")
        shared_project.group_id = group.id
        await db_session.flush()

        results, total = await project_repo.list_accessible_for_user(member.id, limit=50, offset=0)

        assert total == 2
        assert {p.id for p in results} == {own_project.id, shared_project.id}

    async def test_list_accessible_for_user_does_not_duplicate_when_owner_is_also_group_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="lafu-nodup@example.com")
        project_repo = ProjectRepository(db_session)
        group_repo = GroupRepository(db_session)
        group = await group_repo.create(name="Team", owner_user_id=owner.id)
        project = await project_repo.create(user_id=owner.id, name="Own and linked to own group")
        project.group_id = group.id
        await db_session.flush()

        results, total = await project_repo.list_accessible_for_user(owner.id, limit=50, offset=0)

        assert total == 1
        assert [p.id for p in results] == [project.id]

    async def test_list_accessible_for_user_excludes_group_project_for_non_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="lafu-excl-owner@example.com")
        stranger = await _make_user(db_session, email="lafu-excl-stranger@example.com")
        project_repo = ProjectRepository(db_session)
        group_repo = GroupRepository(db_session)
        group = await group_repo.create(name="Team", owner_user_id=owner.id)
        shared_project = await project_repo.create(user_id=owner.id, name="Shared")
        shared_project.group_id = group.id
        await db_session.flush()

        results, total = await project_repo.list_accessible_for_user(
            stranger.id, limit=50, offset=0
        )

        assert results == []
        assert total == 0

    async def test_list_accessible_for_user_regression_matches_old_strict_behavior_with_no_groups(
        self, db_session: AsyncSession
    ) -> None:
        """AD-018 non-regression: a v1 user who never touches groups gets the
        same set of projects (only their own, none of another user's) and
        the same total from list_accessible_for_user as the old strict
        list_for_user did. Order is intentionally not asserted here: within
        one transaction Postgres's `now()` is transaction-start-time, so
        project_a1/project_a2's `created_at` are identical by construction —
        the repository's `(created_at, id)` ordering only guarantees a
        *stable* order across repeated calls, not insertion order, so
        asserting a specific list order here would be flaky by construction
        (id is a random UUID, unrelated to creation order).
        """
        user_a = await _make_user(db_session, email="a-regress@example.com")
        user_b = await _make_user(db_session, email="b-regress@example.com")
        repo = ProjectRepository(db_session)
        project_a1 = await repo.create(user_id=user_a.id, name="A1")
        project_a2 = await repo.create(user_id=user_a.id, name="A2")
        await repo.create(user_id=user_b.id, name="B1")

        results, total = await repo.list_accessible_for_user(user_a.id, limit=50, offset=0)

        assert total == 2
        assert {p.id for p in results} == {project_a1.id, project_a2.id}
        assert all(p.user_id == user_a.id for p in results)

    async def test_list_accessible_for_user_paginates_with_total_reflecting_full_count(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, email="lafu-page@example.com")
        repo = ProjectRepository(db_session)
        for i in range(3):
            await repo.create(user_id=user.id, name=f"P{i}")

        page, total = await repo.list_accessible_for_user(user.id, limit=2, offset=0)

        assert total == 3
        assert len(page) == 2


class TestProjectRepositoryGetAccessibleForUser:
    async def test_get_accessible_for_user_returns_project_for_direct_owner(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, email="gafu-owner@example.com")
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Mine")

        found = await repo.get_accessible_for_user(project.id, user.id)

        assert found is not None
        assert found.id == project.id

    async def test_get_accessible_for_user_returns_project_for_group_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="gafu-owner2@example.com")
        member = await _make_user(db_session, email="gafu-member2@example.com")
        project_repo = ProjectRepository(db_session)
        group_repo = GroupRepository(db_session)
        group = await group_repo.create(name="Team", owner_user_id=owner.id)
        await group_repo.add_member(group.id, member.id, GroupRole.MEMBER)
        project = await project_repo.create(user_id=owner.id, name="Shared")
        project.group_id = group.id
        await db_session.flush()

        found = await project_repo.get_accessible_for_user(project.id, member.id)

        assert found is not None
        assert found.id == project.id

    async def test_get_accessible_for_user_returns_none_for_neither_owner_nor_group_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="gafu-owner3@example.com")
        stranger = await _make_user(db_session, email="gafu-stranger3@example.com")
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=owner.id, name="Private")

        found = await repo.get_accessible_for_user(project.id, stranger.id)

        assert found is None

    async def test_get_accessible_for_user_returns_none_for_group_project_when_not_a_member(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="gafu-owner4@example.com")
        stranger = await _make_user(db_session, email="gafu-stranger4@example.com")
        project_repo = ProjectRepository(db_session)
        group_repo = GroupRepository(db_session)
        group = await group_repo.create(name="Team", owner_user_id=owner.id)
        project = await project_repo.create(user_id=owner.id, name="Shared")
        project.group_id = group.id
        await db_session.flush()

        found = await project_repo.get_accessible_for_user(project.id, stranger.id)

        assert found is None


class TestProjectRepositoryGetForUser:
    async def test_get_for_user_returns_project_for_owner(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Mine")

        found = await repo.get_for_user(project.id, user.id)

        assert found is not None
        assert found.id == project.id
        assert found.user_id == user.id

    async def test_get_for_user_returns_none_for_another_users_project(
        self, db_session: AsyncSession
    ) -> None:
        owner = await _make_user(db_session, email="owner-gfu@example.com")
        other = await _make_user(db_session, email="other-gfu@example.com")
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=owner.id, name="Owner's project")

        found = await repo.get_for_user(project.id, other.id)

        assert found is None


class TestProjectRepositoryRename:
    async def test_rename_updates_name(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Old name")

        renamed = await repo.rename(project.id, "New name")

        assert renamed.id == project.id
        assert renamed.name == "New name"


class TestProjectRepositoryDelete:
    async def test_delete_removes_project(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="To delete")

        await repo.delete(project.id)

        remaining, total = await repo.list_accessible_for_user(user.id, limit=50, offset=0)
        assert remaining == []
        assert total == 0


class TestProjectRepositoryCountTasks:
    async def test_count_tasks_returns_zero_when_no_tasks(self, db_session: AsyncSession) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="Empty project")

        count = await repo.count_tasks(project.id)

        assert count == 0

    async def test_count_tasks_returns_number_of_tasks_in_project(
        self, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session)
        repo = ProjectRepository(db_session)
        project = await repo.create(user_id=user.id, name="With tasks")
        db_session.add(Task(project_id=project.id, title="Task 1"))
        db_session.add(Task(project_id=project.id, title="Task 2"))
        await db_session.flush()

        count = await repo.count_tasks(project.id)

        assert count == 2
