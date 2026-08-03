import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models.group import GroupInvite, GroupRole
from app.repositories.group_invite_repository import GroupInviteRepository
from app.repositories.group_repository import GroupRepository
from app.repositories.project_repository import ProjectRepository
from tests.integration.api.conftest import register_and_login


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


async def _register_and_get_id(client: AsyncClient, email: str) -> uuid.UUID:
    """Registers + logs in a user, returning their id (register_and_login
    doesn't expose it, but the /auth/register response body does).
    """
    register_response = await client.post(
        "/auth/register", json={"email": email, "password": "correct-horse-battery-staple"}
    )
    assert register_response.status_code == 201, register_response.text
    user_id = uuid.UUID(register_response.json()["id"])
    login_response = await client.post(
        "/auth/login", json={"email": email, "password": "correct-horse-battery-staple"}
    )
    assert login_response.status_code == 200, login_response.text
    return user_id


async def _login(client: AsyncClient, email: str) -> None:
    """Re-authenticates as an already-registered user (register_and_login
    always registers first, so it can't be reused to switch back to a user
    registered earlier in the same test).
    """
    login_response = await client.post(
        "/auth/login", json={"email": email, "password": "correct-horse-battery-staple"}
    )
    assert login_response.status_code == 200, login_response.text


class TestCreateGroup:
    async def test_create_group_returns_201(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-create"))

        response = await client.post("/groups", json={"name": "Engineering"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Engineering"
        assert "id" in body

    async def test_create_group_without_session_returns_401(self, client: AsyncClient) -> None:
        response = await client.post("/groups", json={"name": "Engineering"})

        assert response.status_code == 401

    async def test_create_group_name_over_100_chars_returns_422(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-create-422"))

        response = await client.post("/groups", json={"name": "x" * 101})

        assert response.status_code == 422


class TestListGroups:
    async def test_list_groups_returns_own_groups_with_role(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-list-a"))
        created = await client.post("/groups", json={"name": "A's group"})
        assert created.status_code == 201

        response = await client.get("/groups")

        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "A's group"
        assert body["items"][0]["role"] == "owner"
        assert body["total"] == 1
        assert body["limit"] == 50
        assert body["offset"] == 0

    async def test_list_groups_excludes_other_users_groups(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-list-b1"))
        await client.post("/groups", json={"name": "B1's group"})
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-list-b2"))
        response = await client.get("/groups")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_list_groups_respects_limit_and_offset(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-list-page"))
        for name in ["G1", "G2", "G3"]:
            created = await client.post("/groups", json={"name": name})
            assert created.status_code == 201

        first_page = await client.get("/groups", params={"limit": 2, "offset": 0})
        second_page = await client.get("/groups", params={"limit": 2, "offset": 2})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["items"]) == 2
        assert first_body["total"] == 3
        assert first_body["limit"] == 2
        assert first_body["offset"] == 0

        second_body = second_page.json()
        assert len(second_body["items"]) == 1
        assert second_body["total"] == 3
        assert second_body["offset"] == 2

    async def test_list_groups_without_session_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/groups")

        assert response.status_code == 401


class TestRenameGroup:
    async def test_rename_group_updates_name(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-rename"))
        created = await client.post("/groups", json={"name": "Old name"})
        group_id = created.json()["id"]

        response = await client.patch(f"/groups/{group_id}", json={"name": "New name"})

        assert response.status_code == 200
        assert response.json()["name"] == "New name"

    async def test_rename_nonexistent_group_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-rename-404"))

        response = await client.patch(f"/groups/{uuid.uuid4()}", json={"name": "New name"})

        assert response.status_code == 404

    async def test_rename_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-rename-owner"))
        created = await client.post("/groups", json={"name": "Owned by A"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-rename-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.patch(f"/groups/{group_id}", json={"name": "Hijacked"})

        assert response.status_code == 403


class TestDeleteGroup:
    async def test_delete_group_without_linked_projects_returns_204(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-delete-204"))
        created = await client.post("/groups", json={"name": "Empty group"})
        group_id = created.json()["id"]

        response = await client.delete(f"/groups/{group_id}")

        assert response.status_code == 204
        listing = await client.get("/groups")
        assert listing.json()["items"] == []

    async def test_invite_generated_then_group_deleted_makes_accept_return_404(
        self, client: AsyncClient
    ) -> None:
        """Edge case from spec.md: an invite generated for a group with no
        linked projects (so delete is allowed) outlives the group only as
        an orphaned row -- accepting it afterward must 404, same as any
        other unknown/invalid token. Structurally this relies on the
        `ondelete="CASCADE"` FK from group_invites to groups (design.md's
        data model); this test proves the cascade actually fires, rather
        than assuming the migration got it right.
        """
        await register_and_login(client, _unique_email("grp-delete-orphan-invite"))
        created = await client.post("/groups", json={"name": "Soon to be deleted"})
        group_id = created.json()["id"]

        invite_response = await client.post(f"/groups/{group_id}/invites")
        assert invite_response.status_code == 201, invite_response.text
        token = invite_response.json()["token"]

        delete_response = await client.delete(f"/groups/{group_id}")
        assert delete_response.status_code == 204, delete_response.text
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-delete-orphan-invite-acceptor"))
        accept_response = await client.post(f"/invites/{token}/accept")

        assert accept_response.status_code == 404

    async def test_delete_group_with_linked_project_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-delete-409"))
        created_group = await client.post("/groups", json={"name": "Has project"})
        group_id = uuid.UUID(created_group.json()["id"])
        created_project = await client.post("/projects", json={"name": "Linked project"})
        project_id = uuid.UUID(created_project.json()["id"])
        await ProjectRepository(db_session).set_group(project_id, group_id)
        await db_session.commit()

        response = await client.delete(f"/groups/{group_id}")

        assert response.status_code == 409

    async def test_delete_nonexistent_group_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-delete-404"))

        response = await client.delete(f"/groups/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_delete_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-delete-owner"))
        created = await client.post("/groups", json={"name": "Owned by A"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-delete-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.delete(f"/groups/{group_id}")

        assert response.status_code == 403


class TestListGroupMembers:
    async def test_list_members_returns_role_and_joined_at(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_id = await _register_and_get_id(client, _unique_email("grp-members-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        member_id = await _register_and_get_id(client, _unique_email("grp-members-b"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.get(f"/groups/{group_id}/members")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        roles_by_user = {item["user_id"]: item["role"] for item in body["items"]}
        assert roles_by_user[str(owner_id)] == "owner"
        assert roles_by_user[str(member_id)] == "member"
        assert all("created_at" in item for item in body["items"])

    async def test_list_members_readable_by_non_owner_member(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-members-readable-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        # register_and_login leaves the client authenticated as the member
        # (not the owner) — this is the "plain member reads the roster"
        # case that GroupService.list_members deliberately allows (Phase 3
        # judgment call: member-readable, not Owner-only).
        member_id = await _register_and_get_id(client, _unique_email("grp-members-readable-b"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.get(f"/groups/{group_id}/members")

        assert response.status_code == 200
        assert response.json()["total"] == 2

    async def test_list_members_by_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-members-owner2"))
        created = await client.post("/groups", json={"name": "Private team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-members-outsider"))
        response = await client.get(f"/groups/{group_id}/members")

        assert response.status_code == 404

    async def test_list_members_respects_limit_and_offset(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_email = _unique_email("grp-members-page-owner")
        await register_and_login(client, owner_email)
        created = await client.post("/groups", json={"name": "Big team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        for i in range(2):
            member_id = await _register_and_get_id(client, _unique_email(f"grp-members-page-{i}"))
            await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
            await db_session.commit()
            await client.post("/auth/logout")

        login_response = await client.post(
            "/auth/login", json={"email": owner_email, "password": "correct-horse-battery-staple"}
        )
        assert login_response.status_code == 200

        first_page = await client.get(f"/groups/{group_id}/members", params={"limit": 2, "offset": 0})
        second_page = await client.get(f"/groups/{group_id}/members", params={"limit": 2, "offset": 2})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["items"]) == 2
        assert first_body["total"] == 3

        second_body = second_page.json()
        assert len(second_body["items"]) == 1
        assert second_body["total"] == 3
        assert second_body["offset"] == 2


class TestCreateInvite:
    async def test_create_invite_returns_201_with_plain_token(self, client: AsyncClient) -> None:
        owner_id = await _register_and_get_id(client, _unique_email("grp-invite-create-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]

        response = await client.post(f"/groups/{group_id}/invites")

        assert response.status_code == 201
        body = response.json()
        assert isinstance(body["token"], str) and len(body["token"]) > 0
        assert body["created_by_user_id"] == str(owner_id)
        assert "expires_at" in body
        assert "token_hash" not in body

    async def test_create_invite_without_session_returns_401(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-create-401-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        response = await client.post(f"/groups/{group_id}/invites")

        assert response.status_code == 401

    async def test_create_invite_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-create-403-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-invite-create-403-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.post(f"/groups/{group_id}/invites")

        assert response.status_code == 403

    async def test_create_invite_by_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-create-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-create-404-outsider"))
        response = await client.post(f"/groups/{group_id}/invites")

        assert response.status_code == 404

    async def test_eleventh_invite_in_one_hour_returns_429(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-ratelimit-owner"))
        created = await client.post("/groups", json={"name": "Rate limited team"})
        group_id = created.json()["id"]

        for _ in range(10):
            response = await client.post(f"/groups/{group_id}/invites")
            assert response.status_code == 201

        eleventh = await client.post(f"/groups/{group_id}/invites")

        assert eleventh.status_code == 429


class TestListGroupInvites:
    async def test_list_pending_invites_returns_metadata_only(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-list-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        create_response = await client.post(f"/groups/{group_id}/invites")
        assert create_response.status_code == 201

        response = await client.get(f"/groups/{group_id}/invites")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert "id" in item and "expires_at" in item and "created_by_user_id" in item
        assert "token" not in item
        assert "token_hash" not in item

    async def test_list_pending_invites_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-list-403-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-invite-list-403-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.get(f"/groups/{group_id}/invites")

        assert response.status_code == 403

    async def test_list_pending_invites_by_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-list-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-list-404-outsider"))
        response = await client.get(f"/groups/{group_id}/invites")

        assert response.status_code == 404


class TestRevokeInvite:
    async def test_revoke_invite_then_accept_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-revoke-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        create_response = await client.post(f"/groups/{group_id}/invites")
        invite_id = create_response.json()["id"]
        token = create_response.json()["token"]

        revoke_response = await client.delete(f"/groups/{group_id}/invites/{invite_id}")
        assert revoke_response.status_code == 204
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-revoke-acceptor"))
        accept_response = await client.post(f"/invites/{token}/accept")

        assert accept_response.status_code == 404

    async def test_revoke_invite_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-revoke-403-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        create_response = await client.post(f"/groups/{group_id}/invites")
        invite_id = create_response.json()["id"]
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-invite-revoke-403-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.delete(f"/groups/{group_id}/invites/{invite_id}")

        assert response.status_code == 403

    async def test_revoke_unknown_invite_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-revoke-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]

        response = await client.delete(f"/groups/{group_id}/invites/{uuid.uuid4()}")

        assert response.status_code == 404


class TestAcceptInvite:
    async def test_accept_valid_invite_returns_200_and_creates_membership(
        self, client: AsyncClient
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-accept-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        create_response = await client.post(f"/groups/{group_id}/invites")
        token = create_response.json()["token"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-accept-member"))
        response = await client.post(f"/invites/{token}/accept")

        assert response.status_code == 200
        assert response.json()["id"] == group_id

        members = await client.get(f"/groups/{group_id}/members")
        assert members.status_code == 200
        assert members.json()["total"] == 2

    async def test_accept_invite_without_session_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(f"/invites/{uuid.uuid4()}/accept")

        assert response.status_code == 401

    async def test_accept_unknown_token_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-accept-404"))

        response = await client.post("/invites/not-a-real-token/accept")

        assert response.status_code == 404

    async def test_accept_already_consumed_token_returns_409(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-invite-accept-409-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        create_response = await client.post(f"/groups/{group_id}/invites")
        token = create_response.json()["token"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-accept-409-first"))
        first_accept = await client.post(f"/invites/{token}/accept")
        assert first_accept.status_code == 200
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-accept-409-second"))
        second_accept = await client.post(f"/invites/{token}/accept")

        assert second_accept.status_code == 409

    async def test_accept_already_member_returns_409(self, client: AsyncClient) -> None:
        owner_email = _unique_email("grp-invite-accept-already-owner")
        await register_and_login(client, owner_email)
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        first_invite = await client.post(f"/groups/{group_id}/invites")
        first_token = first_invite.json()["token"]
        await client.post("/auth/logout")

        member_email = _unique_email("grp-invite-accept-already-member")
        await register_and_login(client, member_email)
        joined = await client.post(f"/invites/{first_token}/accept")
        assert joined.status_code == 200
        await client.post("/auth/logout")

        login_as_owner = await client.post(
            "/auth/login", json={"email": owner_email, "password": "correct-horse-battery-staple"}
        )
        assert login_as_owner.status_code == 200
        second_invite = await client.post(f"/groups/{group_id}/invites")
        second_token = second_invite.json()["token"]
        await client.post("/auth/logout")

        login_as_member = await client.post(
            "/auth/login", json={"email": member_email, "password": "correct-horse-battery-staple"}
        )
        assert login_as_member.status_code == 200
        response = await client.post(f"/invites/{second_token}/accept")

        assert response.status_code == 409

    async def test_accept_expired_invite_returns_410(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-invite-accept-410-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        create_response = await client.post(f"/groups/{group_id}/invites")
        token = create_response.json()["token"]

        invite = await GroupInviteRepository(db_session).get_by_hash(hash_token(token))
        await db_session.execute(
            update(GroupInvite)
            .where(GroupInvite.id == invite.id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
        )
        await db_session.commit()
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-invite-accept-410-member"))
        response = await client.post(f"/invites/{token}/accept")

        assert response.status_code == 410


class TestRemoveMember:
    async def test_remove_member_by_owner_returns_204_and_revokes_access(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_email = _unique_email("grp-remove-owner")
        await register_and_login(client, owner_email)
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        member_id = await _register_and_get_id(client, _unique_email("grp-remove-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()
        await client.post("/auth/logout")

        await _login(client, owner_email)
        response = await client.delete(f"/groups/{group_id}/members/{member_id}")

        assert response.status_code == 204
        members = await client.get(f"/groups/{group_id}/members")
        assert members.json()["total"] == 1

    async def test_remove_member_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-remove-403-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        target_id = await _register_and_get_id(client, _unique_email("grp-remove-403-target"))
        await GroupRepository(db_session).add_member(group_id, target_id, GroupRole.MEMBER)
        await db_session.commit()
        await client.post("/auth/logout")

        acting_member_id = await _register_and_get_id(client, _unique_email("grp-remove-403-actor"))
        await GroupRepository(db_session).add_member(group_id, acting_member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.delete(f"/groups/{group_id}/members/{target_id}")

        assert response.status_code == 403

    async def test_remove_member_by_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-remove-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-remove-404-outsider"))
        response = await client.delete(f"/groups/{group_id}/members/{uuid.uuid4()}")

        assert response.status_code == 404


class TestLeaveGroup:
    async def test_member_leave_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-leave-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        member_email = _unique_email("grp-leave-member")
        member_id = await _register_and_get_id(client, member_email)
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.post(f"/groups/{group_id}/leave")

        assert response.status_code == 200
        members = await client.get(f"/groups/{group_id}/members")
        assert members.status_code == 404  # no longer a member, access revoked

    async def test_owner_leave_without_transfer_returns_409(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-leave-409-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]

        response = await client.post(f"/groups/{group_id}/leave")

        assert response.status_code == 409

    async def test_leave_by_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-leave-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-leave-404-outsider"))
        response = await client.post(f"/groups/{group_id}/leave")

        assert response.status_code == 404


class TestTransferOwnership:
    async def test_transfer_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-transfer-403-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        target_id = await _register_and_get_id(client, _unique_email("grp-transfer-403-target"))
        await GroupRepository(db_session).add_member(group_id, target_id, GroupRole.MEMBER)
        await db_session.commit()
        await client.post("/auth/logout")

        acting_member_id = await _register_and_get_id(client, _unique_email("grp-transfer-403-actor"))
        await GroupRepository(db_session).add_member(group_id, acting_member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.post(
            f"/groups/{group_id}/transfer-ownership", json={"new_owner_user_id": str(target_id)}
        )

        assert response.status_code == 403

    async def test_transfer_to_non_member_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-transfer-404-owner"))
        created = await client.post("/groups", json={"name": "Team"})
        group_id = created.json()["id"]

        response = await client.post(
            f"/groups/{group_id}/transfer-ownership", json={"new_owner_user_id": str(uuid.uuid4())}
        )

        assert response.status_code == 404

    async def test_transfer_ownership_happy_path_swaps_roles(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_email = _unique_email("grp-transfer-owner")
        owner_id = await _register_and_get_id(client, owner_email)
        created = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created.json()["id"])
        await client.post("/auth/logout")

        new_owner_id = await _register_and_get_id(client, _unique_email("grp-transfer-new-owner"))
        await GroupRepository(db_session).add_member(group_id, new_owner_id, GroupRole.MEMBER)
        await db_session.commit()
        await client.post("/auth/logout")

        await _login(client, owner_email)
        response = await client.post(
            f"/groups/{group_id}/transfer-ownership", json={"new_owner_user_id": str(new_owner_id)}
        )
        assert response.status_code == 200

        members = await client.get(f"/groups/{group_id}/members")
        roles_by_user = {item["user_id"]: item["role"] for item in members.json()["items"]}
        assert roles_by_user[str(new_owner_id)] == "owner"
        assert roles_by_user[str(owner_id)] == "member"


class TestLinkProject:
    async def test_link_own_project_returns_200_and_sets_group_id(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-link-owner"))
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = created_group.json()["id"]
        created_project = await client.post("/projects", json={"name": "Owned project"})
        project_id = created_project.json()["id"]

        response = await client.post(f"/groups/{group_id}/projects/{project_id}/link")

        assert response.status_code == 200
        assert response.json()["group_id"] == group_id

    async def test_link_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_email = _unique_email("grp-link-403-owner")
        await register_and_login(client, owner_email)
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created_group.json()["id"])
        created_project = await client.post("/projects", json={"name": "Owned project"})
        project_id = created_project.json()["id"]
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-link-403-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.post(f"/groups/{group_id}/projects/{project_id}/link")

        assert response.status_code == 403

    async def test_link_project_not_owned_by_acting_user_returns_404(
        self, client: AsyncClient
    ) -> None:
        owner_email = _unique_email("grp-link-404-owner")
        await register_and_login(client, owner_email)
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = created_group.json()["id"]
        await client.post("/auth/logout")

        await register_and_login(client, _unique_email("grp-link-404-other"))
        created_project = await client.post("/projects", json={"name": "Other's project"})
        project_id = created_project.json()["id"]
        await client.post("/auth/logout")

        await _login(client, owner_email)
        response = await client.post(f"/groups/{group_id}/projects/{project_id}/link")

        assert response.status_code == 404

    async def test_link_already_linked_project_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-link-409-owner"))
        first_group = await client.post("/groups", json={"name": "First team"})
        first_group_id = uuid.UUID(first_group.json()["id"])
        second_group = await client.post("/groups", json={"name": "Second team"})
        second_group_id = second_group.json()["id"]
        created_project = await client.post("/projects", json={"name": "Owned project"})
        project_id = uuid.UUID(created_project.json()["id"])
        await ProjectRepository(db_session).set_group(project_id, first_group_id)
        await db_session.commit()

        response = await client.post(f"/groups/{second_group_id}/projects/{project_id}/link")

        assert response.status_code == 409


class TestUnlinkProject:
    async def test_unlink_linked_project_returns_200_and_clears_group_id(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await register_and_login(client, _unique_email("grp-unlink-owner"))
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created_group.json()["id"])
        created_project = await client.post("/projects", json={"name": "Owned project"})
        project_id = uuid.UUID(created_project.json()["id"])
        await ProjectRepository(db_session).set_group(project_id, group_id)
        await db_session.commit()

        response = await client.post(f"/groups/{group_id}/projects/{project_id}/unlink")

        assert response.status_code == 200
        assert response.json()["group_id"] is None

    async def test_unlink_by_non_owner_member_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        owner_email = _unique_email("grp-unlink-403-owner")
        await register_and_login(client, owner_email)
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = uuid.UUID(created_group.json()["id"])
        created_project = await client.post("/projects", json={"name": "Owned project"})
        project_id = uuid.UUID(created_project.json()["id"])
        await ProjectRepository(db_session).set_group(project_id, group_id)
        await db_session.commit()
        await client.post("/auth/logout")

        member_id = await _register_and_get_id(client, _unique_email("grp-unlink-403-member"))
        await GroupRepository(db_session).add_member(group_id, member_id, GroupRole.MEMBER)
        await db_session.commit()

        response = await client.post(f"/groups/{group_id}/projects/{project_id}/unlink")

        assert response.status_code == 403

    async def test_unlink_project_not_linked_to_group_returns_404(self, client: AsyncClient) -> None:
        await register_and_login(client, _unique_email("grp-unlink-404-owner"))
        created_group = await client.post("/groups", json={"name": "Team"})
        group_id = created_group.json()["id"]
        created_project = await client.post("/projects", json={"name": "Unlinked project"})
        project_id = created_project.json()["id"]

        response = await client.post(f"/groups/{group_id}/projects/{project_id}/unlink")

        assert response.status_code == 404
