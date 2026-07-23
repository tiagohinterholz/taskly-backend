from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.storage.backend import StorageError
from app.storage.s3 import S3StorageBackend


def _client_error(operation: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "500", "Message": "internal error"}},
        operation_name=operation,
    )


class TestS3StorageBackend:
    def test_save_calls_put_object_and_returns_key(self) -> None:
        mock_client = MagicMock()
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        reference = backend.save("tasks/1/photo.png", b"binary-data", "image/png")

        mock_client.put_object.assert_called_once_with(
            Bucket="taskly-attachments",
            Key="tasks/1/photo.png",
            Body=b"binary-data",
            ContentType="image/png",
        )
        assert reference == "tasks/1/photo.png"

    def test_delete_calls_delete_object(self) -> None:
        mock_client = MagicMock()
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        backend.delete("tasks/1/photo.png")

        mock_client.delete_object.assert_called_once_with(
            Bucket="taskly-attachments", Key="tasks/1/photo.png"
        )

    def test_save_raises_storage_error_when_s3_client_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.put_object.side_effect = _client_error("PutObject")
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        with pytest.raises(StorageError):
            backend.save("tasks/1/photo.png", b"binary-data", "image/png")

    def test_delete_raises_storage_error_when_s3_client_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = _client_error("DeleteObject")
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        with pytest.raises(StorageError):
            backend.delete("tasks/1/photo.png")
