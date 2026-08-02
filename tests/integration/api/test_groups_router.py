import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import GroupRole
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
