"""大文件（简历 PDF、录音转写等）放对象存储，数据库只记对象名。对象内容同样按账户加密。"""

from __future__ import annotations

import threading
from typing import Protocol


class BlobStore(Protocol):
    def put(self, name: str, data: bytes) -> None: ...
    def get(self, name: str) -> bytes: ...
    def delete(self, name: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...


class MemoryBlobs:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, name: str, data: bytes) -> None:
        with self._lock:
            self.objects[name] = bytes(data)

    def get(self, name: str) -> bytes:
        with self._lock:
            return self.objects[name]

    def delete(self, name: str) -> None:
        with self._lock:
            self.objects.pop(name, None)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            for k in [k for k in self.objects if k.startswith(prefix)]:
                self.objects.pop(k)


class GcsBlobs:
    def __init__(self, bucket: str):
        self.bucket = bucket

    def put(self, name: str, data: bytes) -> None:
        from joblander import gcp
        gcp.gcs_upload(self.bucket, name, data)

    def get(self, name: str) -> bytes:
        from joblander import gcp
        return gcp.gcs_download(self.bucket, name)

    def delete(self, name: str) -> None:
        from joblander import gcp
        gcp.gcs_delete(self.bucket, name)

    def delete_prefix(self, prefix: str) -> None:
        from joblander import gcp
        for name in gcp.gcs_list(self.bucket, prefix):
            gcp.gcs_delete(self.bucket, name)
