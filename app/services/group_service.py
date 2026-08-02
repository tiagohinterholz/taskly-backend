import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_opaque_token, hash_token
from app.models.group import Group, GroupInvite, GroupMembership, GroupRole
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository

_INVITE_TOKEN_TTL = timedelta(days=7)
_INVITE_RATE_LIMIT_MAX = 10
_INVITE_RATE_LIMIT_WINDOW = timedelta(hours=1)


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


class InviteNotFoundError(Exception):
    """Raised by accept_invite() when the token is unknown or revoked (same
    exception either way, so a revoked token can't be distinguished from an
    invalid one), and by revoke_invite() when the invite doesn't exist or
    doesn't belong to the given group.
    """


class InviteExpiredError(Exception):
    """Raised by accept_invite() when the token's expires_at is in the past."""


class InviteAlreadyUsedError(Exception):
    """Raised by accept_invite() when the token has already been consumed
    (single-use — GRP-03 AC5).
    """


class AlreadyMemberError(Exception):
    """Raised by accept_invite() when the acting user already has a
    membership in the invite's group.
    """


class InviteRateLimitExceededError(Exception):
    """Raised by create_invite() when the Owner has generated 10+ invites
    for this group within the last rolling hour.
    """


class NotGroupMemberError(Exception):
    """Raised by transfer_ownership() when the proposed new owner has no
    existing membership in the group.
    """


class SoleOwnerCannotLeaveError(Exception):
    """Raised by leave() when the acting user is the group's Owner — a group
    can never end up without an Owner, so the Owner must transfer ownership
    first (GRP-08 AC3).
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
        invite_rate_limit: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._group_repository = group_repository
        self._group_invite_repository = group_invite_repository
        self._project_repository = project_repository
        # Rate-limits create_invite() per (group_id, owner_user_id). A fresh
        # dict per instance by default; a router-layer factory can inject a
        # module-level shared dict (mirroring AuthService's
        # _shared_failed_attempts pattern) so the limit survives across the
        # per-request service instances — that wiring is a later phase.
        self._invite_attempts: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = (
            invite_rate_limit if invite_rate_limit is not None else {}
        )

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

    async def create_invite(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID
    ) -> tuple[GroupInvite, str]:
        await self._require_owner(acting_user_id, group_id)
        self._check_invite_rate_limit(group_id, acting_user_id)

        plain_token = generate_opaque_token()
        token_hash = hash_token(plain_token)
        expires_at = datetime.now(timezone.utc) + _INVITE_TOKEN_TTL
        invite = await self._group_invite_repository.create(
            group_id, acting_user_id, token_hash, expires_at
        )
        self._record_invite_attempt(group_id, acting_user_id)
        await self._session.commit()
        return invite, plain_token

    async def accept_invite(self, acting_user_id: uuid.UUID, token: str) -> Group:
        token_hash = hash_token(token)
        invite = await self._group_invite_repository.get_by_hash(token_hash)
        if invite is None or invite.revoked_at is not None:
            raise InviteNotFoundError()
        now = datetime.now(timezone.utc)
        if invite.expires_at < now:
            raise InviteExpiredError()
        if invite.consumed_at is not None:
            raise InviteAlreadyUsedError()

        existing_membership = await self._group_repository.get_membership(
            invite.group_id, acting_user_id
        )
        if existing_membership is not None:
            raise AlreadyMemberError()

        await self._group_repository.add_member(invite.group_id, acting_user_id, GroupRole.MEMBER)
        await self._group_invite_repository.mark_consumed(invite.id)
        group = await self._group_repository.get_by_id(invite.group_id)
        await self._session.commit()
        return group

    async def revoke_invite(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID, invite_id: uuid.UUID
    ) -> None:
        await self._require_owner(acting_user_id, group_id)
        invite = await self._group_invite_repository.get_by_id(invite_id)
        if invite is None or invite.group_id != group_id:
            raise InviteNotFoundError()
        await self._group_invite_repository.mark_revoked(invite.id)
        await self._session.commit()

    async def list_pending_invites(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[GroupInvite], int]:
        await self._require_owner(acting_user_id, group_id)
        return await self._group_invite_repository.list_pending(group_id, limit, offset)

    def _check_invite_rate_limit(self, group_id: uuid.UUID, acting_user_id: uuid.UUID) -> None:
        key = (group_id, acting_user_id)
        now = datetime.now(timezone.utc)
        attempts = [t for t in self._invite_attempts.get(key, []) if now - t < _INVITE_RATE_LIMIT_WINDOW]
        self._invite_attempts[key] = attempts
        if len(attempts) >= _INVITE_RATE_LIMIT_MAX:
            raise InviteRateLimitExceededError(group_id)

    def _record_invite_attempt(self, group_id: uuid.UUID, acting_user_id: uuid.UUID) -> None:
        key = (group_id, acting_user_id)
        self._invite_attempts.setdefault(key, []).append(datetime.now(timezone.utc))

    async def remove_member(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID, target_user_id: uuid.UUID
    ) -> None:
        await self._require_owner(acting_user_id, group_id)
        await self._group_repository.remove_member(group_id, target_user_id)
        await self._session.commit()

    async def leave(self, acting_user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        membership = await self._group_repository.get_membership(group_id, acting_user_id)
        if membership is None:
            raise GroupNotFoundError(group_id)
        if membership.role == GroupRole.OWNER:
            raise SoleOwnerCannotLeaveError(group_id)
        await self._group_repository.remove_member(group_id, acting_user_id)
        await self._session.commit()

    async def transfer_ownership(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID, new_owner_user_id: uuid.UUID
    ) -> None:
        await self._require_owner(acting_user_id, group_id)
        new_owner_membership = await self._group_repository.get_membership(
            group_id, new_owner_user_id
        )
        if new_owner_membership is None:
            raise NotGroupMemberError(new_owner_user_id)

        # Demote the current owner FIRST, then promote the new owner: the
        # DB's partial unique index (one OWNER row per group) is checked
        # per-statement, so promoting before demoting would transiently
        # create two OWNER rows and violate the constraint.
        await self._group_repository.set_role(group_id, acting_user_id, GroupRole.MEMBER)
        await self._group_repository.set_role(group_id, new_owner_user_id, GroupRole.OWNER)
        await self._session.commit()

    async def _require_owner(
        self, acting_user_id: uuid.UUID, group_id: uuid.UUID
    ) -> GroupMembership:
        membership = await self._group_repository.get_membership(group_id, acting_user_id)
        if membership is None:
            raise GroupNotFoundError(group_id)
        if membership.role != GroupRole.OWNER:
            raise NotGroupOwnerError(group_id)
        return membership
