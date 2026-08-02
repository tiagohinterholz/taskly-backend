from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.user_repository import UserRepository


async def _make_user(db_session: AsyncSession, email: str = "owner@example.com"):
    return await UserRepository(db_session).create(email=email, password_hash="hash")


async def _make_group(db_session: AsyncSession, owner_email: str = "owner@example.com"):
    owner = await _make_user(db_session, owner_email)
    group = await GroupRepository(db_session).create(name="Team", owner_user_id=owner.id)
    return group, owner


class TestGroupInviteRepositoryCreate:
    async def test_create_persists_invite_for_group(self, db_session: AsyncSession) -> None:
        group, owner = await _make_group(db_session, "create-owner@example.com")
        repo = GroupInviteRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        invite = await repo.create(
            group_id=group.id,
            created_by_user_id=owner.id,
            token_hash="hash-abc",
            expires_at=expires_at,
        )

        assert invite.id is not None
        assert invite.group_id == group.id
        assert invite.created_by_user_id == owner.id
        assert invite.token_hash == "hash-abc"
        assert invite.expires_at == expires_at
        assert invite.consumed_at is None
        assert invite.revoked_at is None


class TestGroupInviteRepositoryGetByHash:
    async def test_get_by_hash_returns_existing_invite(self, db_session: AsyncSession) -> None:
        group, owner = await _make_group(db_session, "gbh-owner@example.com")
        repo = GroupInviteRepository(db_session)
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        created = await repo.create(group.id, owner.id, "hash-xyz", expires_at)

        found = await repo.get_by_hash("hash-xyz")

        assert found is not None
        assert found.id == created.id

    async def test_get_by_hash_returns_none_when_not_found(self, db_session: AsyncSession) -> None:
        repo = GroupInviteRepository(db_session)

        found = await repo.get_by_hash("does-not-exist")

        assert found is None


class TestGroupInviteRepositoryListPending:
    async def test_list_pending_excludes_consumed_revoked_and_expired(
        self, db_session: AsyncSession
    ) -> None:
        group, owner = await _make_group(db_session, "lp-owner@example.com")
        repo = GroupInviteRepository(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        past = datetime.now(timezone.utc) - timedelta(days=1)

        pending = await repo.create(group.id, owner.id, "hash-pending", future)
        consumed = await repo.create(group.id, owner.id, "hash-consumed", future)
        await repo.mark_consumed(consumed.id)
        revoked = await repo.create(group.id, owner.id, "hash-revoked", future)
        await repo.mark_revoked(revoked.id)
        await repo.create(group.id, owner.id, "hash-expired", past)

        items, total = await repo.list_pending(group.id, limit=50, offset=0)

        assert total == 1
        assert [i.id for i in items] == [pending.id]

    async def test_list_pending_paginates_with_total_reflecting_full_count(
        self, db_session: AsyncSession
    ) -> None:
        group, owner = await _make_group(db_session, "lpp-owner@example.com")
        repo = GroupInviteRepository(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        for i in range(3):
            await repo.create(group.id, owner.id, f"hash-{i}", future)

        page, total = await repo.list_pending(group.id, limit=2, offset=0)

        assert total == 3
        assert len(page) == 2

    async def test_list_pending_scoped_to_the_given_group(self, db_session: AsyncSession) -> None:
        group_a, owner_a = await _make_group(db_session, "lps-a@example.com")
        group_b, owner_b = await _make_group(db_session, "lps-b@example.com")
        repo = GroupInviteRepository(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        invite_a = await repo.create(group_a.id, owner_a.id, "hash-a", future)
        await repo.create(group_b.id, owner_b.id, "hash-b", future)

        items, total = await repo.list_pending(group_a.id, limit=50, offset=0)

        assert total == 1
        assert [i.id for i in items] == [invite_a.id]


class TestGroupInviteRepositoryMarkConsumed:
    async def test_mark_consumed_sets_consumed_at(self, db_session: AsyncSession) -> None:
        group, owner = await _make_group(db_session, "mc-owner@example.com")
        repo = GroupInviteRepository(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        invite = await repo.create(group.id, owner.id, "hash-consume", future)

        await repo.mark_consumed(invite.id)

        found = await repo.get_by_hash("hash-consume")
        assert found is not None
        assert found.consumed_at is not None


class TestGroupInviteRepositoryMarkRevoked:
    async def test_mark_revoked_sets_revoked_at(self, db_session: AsyncSession) -> None:
        group, owner = await _make_group(db_session, "mr-owner@example.com")
        repo = GroupInviteRepository(db_session)
        future = datetime.now(timezone.utc) + timedelta(days=7)
        invite = await repo.create(group.id, owner.id, "hash-revoke", future)

        await repo.mark_revoked(invite.id)

        found = await repo.get_by_hash("hash-revoke")
        assert found is not None
        assert found.revoked_at is not None
