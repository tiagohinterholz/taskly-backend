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

    def test_get_url_returns_the_presigned_url_from_the_client(self) -> None:
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = (
            "https://taskly-attachments.s3.amazonaws.com/tasks/1/photo.png?X-Amz-Signature=abc"
        )
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        url = backend.get_url("tasks/1/photo.png")

        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "taskly-attachments", "Key": "tasks/1/photo.png"},
            ExpiresIn=3600,
        )
        assert url == "https://taskly-attachments.s3.amazonaws.com/tasks/1/photo.png?X-Amz-Signature=abc"

    def test_get_url_raises_storage_error_when_s3_client_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.generate_presigned_url.side_effect = _client_error("GeneratePresignedUrl")
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        with pytest.raises(StorageError):
            backend.get_url("tasks/1/photo.png")

    def test_read_returns_the_object_body_bytes(self) -> None:
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"binary-data"
        mock_client.get_object.return_value = {"Body": mock_body}
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        content = backend.read("tasks/1/photo.png")

        mock_client.get_object.assert_called_once_with(
            Bucket="taskly-attachments", Key="tasks/1/photo.png"
        )
        assert content == b"binary-data"

    def test_read_raises_storage_error_when_s3_client_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.get_object.side_effect = _client_error("GetObject")
        backend = S3StorageBackend(bucket="taskly-attachments", client=mock_client)

        with pytest.raises(StorageError):
            backend.read("tasks/1/photo.png")
