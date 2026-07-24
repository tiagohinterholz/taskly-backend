import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository


async def _make_task(db_session: AsyncSession):
    user = await UserRepository(db_session).create(
        email=f"att-repo-owner-{uuid.uuid4()}@example.com", password_hash="hash"
    )
    project = await ProjectRepository(db_session).create(user_id=user.id, name="Project")
    return await TaskRepository(db_session).create(project_id=project.id, title="Task")


class TestAttachmentRepositoryGetForTask:
    async def test_get_for_task_returns_attachment_for_the_owning_task(
        self, db_session: AsyncSession
    ) -> None:
        task = await _make_task(db_session)
        repo = AttachmentRepository(db_session)
        attachment = await repo.create(
            task_id=task.id,
            filename="notes.txt",
            storage_key="tasks/1/notes.txt",
            content_type="text/plain",
            size_bytes=11,
        )

        found = await repo.get_for_task(attachment.id, task.id)

        assert found is not None
        assert found.id == attachment.id
        assert found.task_id == task.id

    async def test_get_for_task_returns_none_for_attachment_of_a_different_task(
        self, db_session: AsyncSession
    ) -> None:
        task_a = await _make_task(db_session)
        task_b = await _make_task(db_session)
        repo = AttachmentRepository(db_session)
        attachment = await repo.create(
            task_id=task_a.id,
            filename="notes.txt",
            storage_key="tasks/1/notes.txt",
            content_type="text/plain",
            size_bytes=11,
        )

        found = await repo.get_for_task(attachment.id, task_b.id)

        assert found is None
