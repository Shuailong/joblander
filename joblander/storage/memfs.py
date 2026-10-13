"""内存后端：TenantFS 的参考实现。测试用它验证 CloudPath 与 pathlib 的行为一致、账户之间互相看不见；
本机也可以用它把多租户形态整个跑起来（重启即丢）。"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from joblander.storage.cloudpath import Entry


def _parent(key: str) -> str:
    return key.rsplit("/", 1)[0] if "/" in key else ""


class MemoryStore:
    def __init__(self) -> None:
        self._tenants: dict[str, dict[str, tuple[bool, bytes, int]]] = {}
        self._lock = threading.RLock()
        self._locks: dict[tuple[str, str], threading.RLock] = {}

    def create_tenant(self, tenant_id: str) -> None:
        with self._lock:
            self._tenants.setdefault(tenant_id, {})

    def delete_tenant(self, tenant_id: str) -> None:
        with self._lock:
            self._tenants.pop(tenant_id, None)

    def has_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants

    def tenants(self) -> list[str]:
        return sorted(self._tenants)

    def fs(self, tenant_id: str) -> "MemoryTenantFS":
        if tenant_id not in self._tenants:
            raise KeyError(f"账户不存在：{tenant_id}")
        return MemoryTenantFS(self, tenant_id)

    @contextmanager
    def lock(self, tenant_id: str, name: str, blocking: bool = True) -> Iterator[bool]:
        with self._lock:
            lk = self._locks.setdefault((tenant_id, name), threading.RLock())
        got = lk.acquire(blocking=blocking)
        try:
            yield got
        finally:
            if got:
                lk.release()


class MemoryTenantFS:
    def __init__(self, store: MemoryStore, tenant_id: str):
        self.store = store
        self.tenant_id = tenant_id

    @property
    def _files(self) -> dict[str, tuple[bool, bytes, int]]:
        return self.store._tenants[self.tenant_id]

    def stat(self, key: str) -> Entry | None:
        if key == "":
            return Entry("", True)
        with self.store._lock:
            v = self._files.get(key)
        if v is None:
            return None
        is_dir, data, mtime = v
        return Entry(key, is_dir, len(data), mtime)

    def read(self, key: str) -> bytes:
        with self.store._lock:
            v = self._files.get(key)
        if v is None or v[0]:
            raise FileNotFoundError(key)
        return v[1]

    def write(self, key: str, data: bytes) -> None:
        with self.store._lock:
            self._files[key] = (False, bytes(data), time.time_ns())

    def append(self, key: str, data: bytes) -> None:
        with self.store._lock:
            old = self._files.get(key)
            base = old[1] if old and not old[0] else b""
            self._files[key] = (False, base + bytes(data), time.time_ns())

    def mkdir(self, key: str) -> None:
        with self.store._lock:
            self._files[key] = (True, b"", time.time_ns())

    def rmdir(self, key: str) -> None:
        with self.store._lock:
            self._files.pop(key, None)

    def delete(self, key: str) -> None:
        with self.store._lock:
            self._files.pop(key, None)

    def children(self, key: str) -> list[Entry]:
        with self.store._lock:
            items = [(k, v) for k, v in self._files.items() if k and _parent(k) == key]
        return [Entry(k, v[0], len(v[1]), v[2]) for k, v in sorted(items)]

    def descendants(self, key: str) -> list[Entry]:
        prefix = key + "/" if key else ""
        with self.store._lock:
            items = [(k, v) for k, v in self._files.items() if k and k.startswith(prefix)]
        return [Entry(k, v[0], len(v[1]), v[2]) for k, v in sorted(items)]

    def rename(self, src: str, dst: str) -> None:
        with self.store._lock:
            files = self._files
            moved = {k: v for k, v in files.items() if k == src or k.startswith(src + "/")}
            if dst in files and files[dst][0] and dst not in moved:
                files.pop(dst)                  # 空目录目标被替换（调用方已确认为空）
            for k in moved:
                files.pop(k)
            for k, v in moved.items():
                files[dst + k[len(src):]] = v
