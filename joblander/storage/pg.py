"""Postgres 后端：账户空间的文件按账户隔离（强制行级安全）、按账户加密，大文件进对象存储。

表：
- tenants      账户与其包裹后的数据密钥
- ws_files     账户空间里的文件与目录（文件内容加密；大文件只记对象名）
- ws_appends   追加写的分块（事件日志等只增文件：追加不重写整份）
- tasks        后台任务的状态（跨实例可查，重启不丢）

每个事务先 set_config('app.tenant_id', …, true)；策略只放行该账户的行，没设置时一行都看不到。
引擎用的数据库角色不拥有这些表、没有 BYPASSRLS，绕不过策略。
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from joblander.storage import crypto
from joblander.storage.blobs import BlobStore
from joblander.storage.cloudpath import Entry

MIGRATIONS: list[str] = [
    # 1：账户空间与任务
    """
    create table if not exists tenants (
        id           text primary key,
        wrapped_dek  bytea not null,
        kek_id       text not null,
        status       text not null default 'active',
        created_at   timestamptz not null default now()
    );
    create table if not exists ws_files (
        tenant_id  text not null references tenants(id) on delete cascade,
        path       text not null,
        parent     text not null,
        is_dir     boolean not null,
        file_id    uuid not null,
        size       bigint not null default 0,
        mtime_ns   bigint not null,
        version    bigint not null default 1,
        data       bytea,
        blob       text,
        primary key (tenant_id, path)
    );
    create index if not exists ws_files_parent on ws_files (tenant_id, parent);
    create table if not exists ws_appends (
        tenant_id  text not null references tenants(id) on delete cascade,
        file_id    uuid not null,
        seq        bigint generated always as identity,
        data       bytea not null,
        primary key (tenant_id, file_id, seq)
    );
    create table if not exists tasks (
        tenant_id    text not null references tenants(id) on delete cascade,
        id           text not null,
        kind         text not null,
        label        text not null,
        status       text not null,
        args         jsonb not null default '{}'::jsonb,
        result       jsonb,
        error        text not null default '',
        started_at   double precision not null,
        ended_at     double precision,
        heartbeat_at double precision,
        primary key (tenant_id, id)
    );
    alter table tenants enable row level security;
    alter table ws_files enable row level security;
    alter table ws_files force row level security;
    alter table ws_appends enable row level security;
    alter table ws_appends force row level security;
    alter table tasks enable row level security;
    alter table tasks force row level security;
    drop policy if exists tenant_rows on tenants;
    create policy tenant_rows on tenants
        using (id = current_setting('app.tenant_id', true))
        with check (id = current_setting('app.tenant_id', true));
    drop policy if exists tenant_rows on ws_files;
    create policy tenant_rows on ws_files
        using (tenant_id = current_setting('app.tenant_id', true))
        with check (tenant_id = current_setting('app.tenant_id', true));
    drop policy if exists tenant_rows on ws_appends;
    create policy tenant_rows on ws_appends
        using (tenant_id = current_setting('app.tenant_id', true))
        with check (tenant_id = current_setting('app.tenant_id', true));
    drop policy if exists tenant_rows on tasks;
    create policy tenant_rows on tasks
        using (tenant_id = current_setting('app.tenant_id', true))
        with check (tenant_id = current_setting('app.tenant_id', true));
    -- 调度器要知道有哪些账户：只暴露 ID，由表的所有者执行（tenants 未强制 RLS，所有者可见全部）
    create or replace function engine_active_tenants() returns setof text
        language sql stable security definer set search_path = public
        as $$ select id from tenants where status = 'active' order by id $$;
    """,
]


def migrate(dsn: str, app_role: str = "engine_app", app_password: str | None = None) -> int:
    """以表所有者身份执行未跑过的迁移，并给应用角色授权。返回执行的条数。

    app_password 给了就顺手建（或改密码）应用角色：只能登录，不能建库建角色、不拥有任何表、
    没有 BYPASSRLS——Cloud SQL 用接口建的用户自带 cloudsqlsuperuser，所以应用角色由这里用 SQL 建。"""
    import psycopg
    from psycopg import sql

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("reset role")                     # 以登录身份（表所有者）执行迁移
        conn.execute("create table if not exists schema_migrations "
                     "(version int primary key, applied_at timestamptz not null default now())")
        done = {r[0] for r in conn.execute("select version from schema_migrations")}
        ran = 0
        for i, stmt in enumerate(MIGRATIONS, start=1):
            if i in done:
                continue
            with conn.transaction():
                conn.execute(stmt)
                conn.execute("insert into schema_migrations (version) values (%s)", (i,))
            ran += 1
        role = sql.Identifier(app_role)
        exists = conn.execute("select 1 from pg_roles where rolname = %s", (app_role,)).fetchone()
        if app_password:
            if exists:     # 只改密码：重申 nosuperuser / nobypassrls 也要超级用户，Cloud SQL 的表所有者不是
                conn.execute(sql.SQL("alter role {} with login password {}")
                             .format(role, sql.Literal(app_password)))
            else:
                conn.execute(sql.SQL("create role {} with login nosuperuser nocreatedb nocreaterole "
                                     "nobypassrls password {}").format(role, sql.Literal(app_password)))
            dbname = conn.execute("select current_database()").fetchone()[0]
            conn.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(dbname), role))
            conn.execute(sql.SQL("grant usage on schema public to {}").format(role))
            exists = True
        if exists:
            conn.execute(sql.SQL("grant select, insert, update, delete on ws_files, ws_appends, tasks to {}")
                         .format(role))
            conn.execute(sql.SQL("grant select, insert, delete on tenants to {}").format(role))
            conn.execute(sql.SQL("grant execute on function engine_active_tenants() to {}").format(role))
        return ran


def lock_key(tenant_id: str, name: str) -> int:
    return int.from_bytes(hashlib.blake2b(f"{tenant_id}:{name}".encode(), digest_size=8).digest(),
                          "big", signed=True)


def _parent(key: str) -> str:
    return key.rsplit("/", 1)[0] if "/" in key else ""


def _like_prefix(key: str) -> str:
    esc = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "/%"


class PgStore:
    def __init__(self, dsn: str, keyring: crypto.Keyring, blobs: BlobStore | None = None, *,
                 blob_threshold: int = 512 * 1024, pool_max: int = 10, role: str | None = None,
                 prepare: bool = True):
        """role：连接后切换到的数据库角色（生产直接以应用角色登录，不需要；测试用超级用户连再切）。
        prepare=False：不用服务端预备语句（前面有事务级连接池、或测试用的 PGlite 时）。"""
        from psycopg import sql
        from psycopg_pool import ConnectionPool

        def configure(conn: Any) -> None:
            if role:
                conn.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
                conn.commit()
        self.pool = ConnectionPool(dsn, min_size=1, max_size=pool_max, open=True, configure=configure,
                                   kwargs={} if prepare else {"prepare_threshold": None})
        self.keyring = keyring
        self.blobs = blobs
        self.blob_threshold = blob_threshold
        self._held = threading.local()
        self._cache: dict[tuple[str, str, int], bytes] = {}
        self._cache_lock = threading.Lock()

    def close(self) -> None:
        self.pool.close()

    # ---------- 事务与密钥 ----------

    @contextmanager
    def tx(self, tenant_id: str) -> Iterator[Any]:
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("select set_config('app.tenant_id', %s, true)", (tenant_id,))
                yield conn

    def _aead(self, conn: Any, tenant_id: str):
        def load(tid: str) -> bytes:
            row = conn.execute("select wrapped_dek from tenants where id = %s", (tid,)).fetchone()
            if row is None:
                raise KeyError(f"账户不存在：{tid}")
            return bytes(row[0])
        return self.keyring.aead(tenant_id, load)

    # ---------- 账户 ----------

    def create_tenant(self, tenant_id: str) -> None:
        wrapped = self.keyring.new_wrapped_dek()
        with self.tx(tenant_id) as conn:
            conn.execute("insert into tenants (id, wrapped_dek, kek_id) values (%s, %s, %s) "
                         "on conflict (id) do nothing", (tenant_id, wrapped, self.keyring.kek.id))

    def has_tenant(self, tenant_id: str) -> bool:
        with self.tx(tenant_id) as conn:
            return conn.execute("select 1 from tenants where id = %s", (tenant_id,)).fetchone() is not None

    def delete_tenant(self, tenant_id: str) -> None:
        """删除账户的全部数据与数据密钥。数据库备份里的副本随时间点恢复窗口（7 天）过期。"""
        with self.tx(tenant_id) as conn:
            conn.execute("delete from tenants where id = %s", (tenant_id,))   # 级联删文件、分块、任务
        self.keyring.forget(tenant_id)
        if self.blobs is not None:
            self.blobs.delete_prefix(f"tenants/{tenant_id}/")
        with self._cache_lock:
            for k in [k for k in self._cache if k[0] == tenant_id]:
                self._cache.pop(k)

    def tenants(self) -> list[str]:
        with self.pool.connection() as conn:
            return [r[0] for r in conn.execute("select * from engine_active_tenants()")]

    def fs(self, tenant_id: str) -> "PgTenantFS":
        return PgTenantFS(self, tenant_id)

    # ---------- 锁 ----------

    @contextmanager
    def lock(self, tenant_id: str, name: str, blocking: bool = True) -> Iterator[bool]:
        """按账户的咨询锁（会话级，持有一条专用连接）。同一线程重入不会自锁。"""
        key = lock_key(tenant_id, name)
        held = self._held.__dict__.setdefault("locks", {})
        if key in held:
            held[key] += 1
            try:
                yield True
            finally:
                held[key] -= 1
            return
        conn = self.pool.getconn()
        try:
            conn.autocommit = True
            if blocking:
                conn.execute("select pg_advisory_lock(%s)", (key,))
                got = True
            else:
                got = bool(conn.execute("select pg_try_advisory_lock(%s)", (key,)).fetchone()[0])
            if not got:
                yield False
                return
            held[key] = 1
            try:
                yield True
            finally:
                held.pop(key, None)
                conn.execute("select pg_advisory_unlock(%s)", (key,))
        finally:
            conn.autocommit = False
            self.pool.putconn(conn)

    # ---------- 读缓存（按版本失效） ----------

    def _cache_get(self, tenant_id: str, file_id: str, version: int) -> bytes | None:
        with self._cache_lock:
            return self._cache.get((tenant_id, file_id, version))

    def _cache_put(self, tenant_id: str, file_id: str, version: int, data: bytes) -> None:
        if len(data) > 4 * 1024 * 1024:
            return
        with self._cache_lock:
            for k in [k for k in self._cache if k[:2] == (tenant_id, file_id)]:
                self._cache.pop(k)
            if len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
            self._cache[(tenant_id, file_id, version)] = data


class PgTenantFS:
    COMPACT_AFTER = 256            # 分块超过这个数就合并回主体

    def __init__(self, store: PgStore, tenant_id: str):
        self.store = store
        self.tenant_id = tenant_id

    def _tx(self):
        return self.store.tx(self.tenant_id)

    def stat(self, key: str) -> Entry | None:
        if key == "":
            return Entry("", True)
        with self._tx() as conn:
            row = conn.execute("select is_dir, size, mtime_ns from ws_files "
                               "where tenant_id = %s and path = %s", (self.tenant_id, key)).fetchone()
        return Entry(key, row[0], row[1], row[2]) if row else None

    def _read_row(self, conn: Any, file_id: str, version: int, data: bytes | None,
                  blob: str | None) -> bytes:
        if version >= 0:
            hit = self.store._cache_get(self.tenant_id, file_id, version)
            if hit is not None:
                return hit
        aead = self.store._aead(conn, self.tenant_id)
        if blob:
            body = crypto.unseal(aead, self.tenant_id, file_id, self.store.blobs.get(blob))
        else:
            body = crypto.unseal(aead, self.tenant_id, file_id, bytes(data or b""))
        chunks = conn.execute("select data from ws_appends where tenant_id = %s and file_id = %s "
                              "order by seq", (self.tenant_id, file_id)).fetchall()
        out = body + b"".join(crypto.unseal(aead, self.tenant_id, file_id, bytes(c[0])) for c in chunks)
        if version >= 0:
            self.store._cache_put(self.tenant_id, file_id, version, out)
        return out

    def read(self, key: str) -> bytes:
        with self._tx() as conn:
            row = conn.execute("select file_id::text, is_dir, version, data, blob from ws_files "
                               "where tenant_id = %s and path = %s", (self.tenant_id, key)).fetchone()
            if row is None or row[1]:
                raise FileNotFoundError(key)
            return self._read_row(conn, row[0], row[2], row[3], row[4])

    def _store_body(self, conn: Any, file_id: str, version: int, data: bytes) -> tuple[bytes | None, str | None]:
        aead = self.store._aead(conn, self.tenant_id)
        sealed = crypto.seal(aead, self.tenant_id, file_id, data)
        if self.store.blobs is not None and len(data) > self.store.blob_threshold:
            name = f"tenants/{self.tenant_id}/{file_id}/{version}"
            self.store.blobs.put(name, sealed)
            return None, name
        return sealed, None

    def write(self, key: str, data: bytes) -> None:
        old_blob = None
        with self._tx() as conn:
            row = conn.execute("select file_id::text, version, blob from ws_files where tenant_id = %s "
                               "and path = %s for update", (self.tenant_id, key)).fetchone()
            file_id = row[0] if row else str(uuid.uuid4())
            version = (row[1] + 1) if row else 1
            old_blob = row[2] if row else None
            body, blob = self._store_body(conn, file_id, version, data)
            conn.execute(
                "insert into ws_files (tenant_id, path, parent, is_dir, file_id, size, mtime_ns, version, data, blob) "
                "values (%s, %s, %s, false, %s, %s, %s, %s, %s, %s) "
                "on conflict (tenant_id, path) do update set is_dir = false, size = excluded.size, "
                "mtime_ns = excluded.mtime_ns, version = excluded.version, data = excluded.data, "
                "blob = excluded.blob",
                (self.tenant_id, key, _parent(key), file_id, len(data), time.time_ns(), version, body, blob))
            if row:
                conn.execute("delete from ws_appends where tenant_id = %s and file_id = %s",
                             (self.tenant_id, file_id))
        if old_blob and self.store.blobs is not None:
            self.store.blobs.delete(old_blob)

    def append(self, key: str, data: bytes) -> None:
        stale: list[str] = []
        with self._tx() as conn:
            self._append(conn, key, data, stale)
        self._drop_blobs(stale)

    def _append(self, conn: Any, key: str, data: bytes, stale: list[str]) -> None:
        row = conn.execute("select file_id::text, version, data, blob from ws_files "
                           "where tenant_id = %s and path = %s for update",
                           (self.tenant_id, key)).fetchone()
        if row is None:                                    # 新文件：追加 = 直接写主体
            file_id = str(uuid.uuid4())
            body, blob = self._store_body(conn, file_id, 1, data)
            conn.execute(
                "insert into ws_files (tenant_id, path, parent, is_dir, file_id, size, mtime_ns, version, data, blob) "
                "values (%s, %s, %s, false, %s, %s, %s, 1, %s, %s)",
                (self.tenant_id, key, _parent(key), file_id, len(data), time.time_ns(), body, blob))
            return
        file_id, version, base_data, base_blob = row
        aead = self.store._aead(conn, self.tenant_id)
        if data:
            conn.execute("insert into ws_appends (tenant_id, file_id, data) values (%s, %s, %s)",
                         (self.tenant_id, file_id, crypto.seal(aead, self.tenant_id, file_id, data)))
        conn.execute("update ws_files set size = size + %s, mtime_ns = %s, version = version + 1 "
                     "where tenant_id = %s and path = %s",
                     (len(data), time.time_ns(), self.tenant_id, key))
        n = conn.execute("select count(*) from ws_appends where tenant_id = %s and file_id = %s",
                         (self.tenant_id, file_id)).fetchone()[0]
        if n <= self.COMPACT_AFTER:
            return
        # 分块太多：主体 + 全部分块合并成新主体，读起来不用再逐块解密
        full = self._read_row(conn, file_id, -1, base_data, base_blob)
        body, blob = self._store_body(conn, file_id, version + 2, full)
        conn.execute("update ws_files set data = %s, blob = %s, version = version + 1, size = %s "
                     "where tenant_id = %s and path = %s",
                     (body, blob, len(full), self.tenant_id, key))
        conn.execute("delete from ws_appends where tenant_id = %s and file_id = %s",
                     (self.tenant_id, file_id))
        if base_blob:
            stale.append(base_blob)

    def mkdir(self, key: str) -> None:
        with self._tx() as conn:
            conn.execute("insert into ws_files (tenant_id, path, parent, is_dir, file_id, mtime_ns) "
                         "values (%s, %s, %s, true, %s, %s) on conflict (tenant_id, path) do nothing",
                         (self.tenant_id, key, _parent(key), str(uuid.uuid4()), time.time_ns()))

    def _delete_rows(self, conn: Any, where: str, params: tuple) -> list[str]:
        rows = conn.execute(f"select file_id::text, blob from ws_files where tenant_id = %s and ({where})",
                            (self.tenant_id, *params)).fetchall()
        if rows:
            conn.execute("delete from ws_appends where tenant_id = %s and file_id = any(%s::uuid[])",
                         (self.tenant_id, [r[0] for r in rows]))
            conn.execute(f"delete from ws_files where tenant_id = %s and ({where})", (self.tenant_id, *params))
        return [r[1] for r in rows if r[1]]

    def _drop_blobs(self, names: list[str]) -> None:
        if self.store.blobs is not None:
            for n in names:
                self.store.blobs.delete(n)

    def delete(self, key: str) -> None:
        with self._tx() as conn:
            blobs = self._delete_rows(conn, "path = %s", (key,))
        self._drop_blobs(blobs)

    rmdir = delete

    def children(self, key: str) -> list[Entry]:
        with self._tx() as conn:
            rows = conn.execute("select path, is_dir, size, mtime_ns from ws_files "
                                "where tenant_id = %s and parent = %s and path <> '' order by path",
                                (self.tenant_id, key)).fetchall()
        return [Entry(r[0], r[1], r[2], r[3]) for r in rows]

    def descendants(self, key: str) -> list[Entry]:
        with self._tx() as conn:
            if key:
                rows = conn.execute("select path, is_dir, size, mtime_ns from ws_files where tenant_id = %s "
                                    "and path like %s escape '\\' order by path",
                                    (self.tenant_id, _like_prefix(key))).fetchall()
            else:
                rows = conn.execute("select path, is_dir, size, mtime_ns from ws_files "
                                    "where tenant_id = %s order by path", (self.tenant_id,)).fetchall()
        return [Entry(r[0], r[1], r[2], r[3]) for r in rows]

    def rename(self, src: str, dst: str) -> None:
        n = len(src) + 1
        with self._tx() as conn:
            blobs = self._delete_rows(conn, "path = %s", (dst,))      # 被覆盖的文件 / 被替换的空目录
            conn.execute(
                "update ws_files set path = %(dst)s || substr(path, %(n)s), "
                "parent = case when path = %(src)s then %(dst_parent)s else %(dst)s || substr(parent, %(n)s) end, "
                "mtime_ns = case when path = %(src)s then %(now)s else mtime_ns end "
                "where tenant_id = %(t)s and (path = %(src)s or path like %(like)s escape '\\')",
                {"dst": dst, "n": n, "src": src, "dst_parent": _parent(dst), "t": self.tenant_id,
                 "like": _like_prefix(src), "now": time.time_ns()})
        self._drop_blobs(blobs)
