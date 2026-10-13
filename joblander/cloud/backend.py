"""按环境变量装配存储后端，并把账户锁、任务登记表接到它上面。

JOBLANDER_STORE=pg（默认）：Postgres（JOBLANDER_DB_DSN）+ 主密钥（JOBLANDER_KMS_KEY 或 JOBLANDER_KEK）
                             + 大文件存储桶（JOBLANDER_BLOB_BUCKET，可选）
JOBLANDER_STORE=memory：内存后端（本机试跑多租户形态 / 测试），重启即丢。
"""

from __future__ import annotations

import os
import threading
from typing import Any

from joblander import tasks, tenancy
from joblander.config import Config, load_tenant_config
from joblander.storage.cloudpath import CloudPath

_store: Any = None
_lock = threading.Lock()


def build_store() -> Any:
    kind = os.environ.get("JOBLANDER_STORE", "pg")
    if kind == "memory":
        from joblander.storage.memfs import MemoryStore
        return MemoryStore()
    from joblander.storage.blobs import GcsBlobs
    from joblander.storage.crypto import Keyring, kek_from_env
    from joblander.storage.pg import PgStore
    dsn = os.environ.get("JOBLANDER_DB_DSN", "") or dsn_from_parts()
    if not dsn:
        raise RuntimeError("缺 JOBLANDER_DB_DSN（或 JOBLANDER_DB_HOST / NAME / USER / PASSWORD）")
    bucket = os.environ.get("JOBLANDER_BLOB_BUCKET", "")
    return PgStore(dsn, Keyring(kek_from_env()), GcsBlobs(bucket) if bucket else None,
                   blob_threshold=int(os.environ.get("JOBLANDER_BLOB_THRESHOLD", str(512 * 1024))),
                   pool_max=int(os.environ.get("JOBLANDER_DB_POOL", "10")))


def dsn_from_parts(prefix: str = "JOBLANDER_DB_") -> str:
    """Cloud Run 上密码来自 Secret Manager（单独一个环境变量），主机是 Cloud SQL 的私有 IP。"""
    host = os.environ.get(prefix + "HOST", "")
    if not host:
        return ""
    from psycopg.conninfo import make_conninfo
    return make_conninfo(host=host, port=os.environ.get(prefix + "PORT", "5432"),
                         dbname=os.environ.get(prefix + "NAME", "engine"),
                         user=os.environ.get(prefix + "USER", "engine_app"),
                         password=os.environ.get(prefix + "PASSWORD", ""),
                         sslmode=os.environ.get(prefix + "SSLMODE", "require"))


def install(store: Any) -> Any:
    """登记后端：账户锁改用后端的锁，任务登记表改用后端的表（Postgres）或内存表。"""
    global _store
    with _lock:
        _store = store
    tenancy.set_lock_backend(store)
    from joblander.storage.pg import PgStore
    tasks.set_table(tasks.PgTable(store) if isinstance(store, PgStore) else tasks.MemoryTable())
    return store


def store() -> Any:
    with _lock:
        if _store is None:
            s = build_store()
        else:
            return _store
    return install(s)


def tenant_root(tenant_id: str) -> CloudPath:
    return CloudPath(store().fs(tenant_id))


def tenant(tenant_id: str) -> tenancy.Tenant:
    return tenancy.Tenant(tenant_id, load_tenant_config(tenant_root(tenant_id)))


def tenant_config(tenant_id: str) -> Config:
    return tenant(tenant_id).cfg
