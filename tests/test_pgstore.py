"""Postgres 后端：行级安全、按账户加密、大文件进对象存储、追加分块与合并、目录改名、删除账户。

需要一个 Postgres（超级用户连接串）：JOBLANDER_TEST_PG_DSN=postgresql://… pytest tests/test_pgstore.py
没配就整份跳过。本机可用 PGlite（Postgres 编译成 WASM，见 OPERATIONS「本机测试 Postgres 后端」）。
测试以超级用户建表，再以不带 BYPASSRLS 的 engine_app 角色读写——与生产一致。
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

DSN = os.environ.get("JOBLANDER_TEST_PG_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="没配 JOBLANDER_TEST_PG_DSN")


@pytest.fixture(scope="module")
def store():
    import psycopg

    from joblander.storage.blobs import MemoryBlobs
    from joblander.storage.crypto import Keyring, LocalKek
    from joblander.storage.pg import PgStore, migrate
    with psycopg.connect(DSN, autocommit=True) as c:
        if not c.execute("select 1 from pg_roles where rolname = 'engine_app'").fetchone():
            c.execute("create role engine_app nologin")
    migrate(DSN, app_role="engine_app")
    s = PgStore(DSN, Keyring(LocalKek(b"k" * 32)), MemoryBlobs(), blob_threshold=1024,
                pool_max=4, role="engine_app", prepare=False)
    yield s
    s.close()


def _su():
    """超级用户视角的连接。PGlite 把所有连接接到同一个会话上，SET ROLE 会串过来，先复位。"""
    import psycopg
    c = psycopg.connect(DSN, autocommit=True)
    c.execute("reset role")
    c.execute("reset app.tenant_id")
    return c


def _is_pglite() -> bool:
    with _su() as c:
        return "emcc" in c.execute("select version()").fetchone()[0]


def _tenant(store) -> str:
    tid = "t" + uuid.uuid4().hex[:12]
    store.create_tenant(tid)
    return tid


def _root(store, tid):
    from joblander.storage.cloudpath import CloudPath
    return CloudPath(store.fs(tid))


def test_matches_pathlib(store, tmp_path):
    from tests.test_cloudpath import scenario
    local = scenario(tmp_path)
    pg = scenario(_root(store, _tenant(store)))
    for i, (a, b) in enumerate(zip(local, pg)):
        assert a == b, f"第 {i} 步不一致：本地 {a!r} ≠ Postgres {b!r}"


def test_row_level_security(store):
    import psycopg
    a, b = _tenant(store), _tenant(store)
    (_root(store, a) / "secret.txt").write_text("A 的薪资底线", encoding="utf-8")
    with _su() as c:
        c.execute("set role engine_app")
        assert c.execute("select count(*) from ws_files").fetchone()[0] == 0          # 没设账户：一行都看不到
        c.execute("select set_config('app.tenant_id', %s, false)", (b,))
        assert c.execute("select count(*) from ws_files where tenant_id = %s", (a,)).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):                     # 以 B 身份写 A 的行
            c.execute("insert into ws_files (tenant_id, path, parent, is_dir, file_id, mtime_ns) "
                      "values (%s, 'x', '', true, gen_random_uuid(), 0)", (a,))
        c.execute("reset role")
        c.execute("reset app.tenant_id")
    assert not (_root(store, b) / "secret.txt").exists()


def test_encrypted_at_rest_and_blobs(store):
    tid = _tenant(store)
    root = _root(store, tid)
    (root / "small.md").write_text("PLAINTEXT-MARKER 小文件", encoding="utf-8")
    big = ("PLAINTEXT-MARKER " * 200).encode()
    (root / "big.pdf").write_bytes(big)
    with _su() as c:
        rows = c.execute("select path, data, blob from ws_files where tenant_id = %s", (tid,)).fetchall()
    by = {r[0]: r for r in rows}
    assert b"PLAINTEXT-MARKER" not in bytes(by["small.md"][1])
    assert by["big.pdf"][1] is None and by["big.pdf"][2]                          # 大文件进对象存储
    assert b"PLAINTEXT-MARKER" not in store.blobs.get(by["big.pdf"][2])
    assert (root / "big.pdf").read_bytes() == big


def test_append_chunks_and_compaction(store, monkeypatch):
    from joblander.storage.pg import PgTenantFS
    monkeypatch.setattr(PgTenantFS, "COMPACT_AFTER", 5)
    root = _root(store, _tenant(store))
    log = root / "event-log.jsonl"
    for i in range(12):
        with log.open("a", encoding="utf-8") as f:
            f.write(f"line {i}\n")
    assert log.read_text(encoding="utf-8").splitlines() == [f"line {i}" for i in range(12)]
    assert log.stat().st_size == len("".join(f"line {i}\n" for i in range(12)))


def test_rename_directory_subtree(store):
    root = _root(store, _tenant(store))
    (root / "co" / "acme" / "jd").mkdir(parents=True)
    (root / "co" / "acme" / "jd" / "a.md").write_text("jd")
    (root / "co" / "acme" / "meta.json").write_text("{}")
    (root / "co" / "acme").rename(root / "co" / "acme-renamed")
    assert sorted(p.name for p in (root / "co").iterdir()) == ["acme-renamed"]
    assert (root / "co" / "acme-renamed" / "jd" / "a.md").read_text() == "jd"
    assert sorted(p.name for p in (root / "co" / "acme-renamed").iterdir()) == ["jd", "meta.json"]


def test_delete_tenant_removes_rows_and_blobs(store):
    tid = _tenant(store)
    (_root(store, tid) / "big.bin").write_bytes(b"x" * 5000)
    assert any(k.startswith(f"tenants/{tid}/") for k in store.blobs.objects)
    store.delete_tenant(tid)
    assert not store.has_tenant(tid)
    assert not any(k.startswith(f"tenants/{tid}/") for k in store.blobs.objects)
    with _su() as c:                                                              # 超级用户视角也一行不剩
        assert c.execute("select count(*) from ws_files where tenant_id = %s", (tid,)).fetchone()[0] == 0


def test_lock_excludes_other_sessions(store):
    if _is_pglite():
        pytest.skip("PGlite 所有连接共用一个会话，会话级咨询锁无法互斥；在真 Postgres 上跑")
    tid = _tenant(store)
    got = []
    with store.lock(tid, "daemon-tick") as first:
        assert first
        def other():
            with store.lock(tid, "daemon-tick", blocking=False) as g:
                got.append(g)
        t = threading.Thread(target=other)
        t.start(); t.join(10)
        with store.lock(tid, "daemon-tick"):                                       # 同一线程重入不自锁
            pass
    assert got == [False]
    with store.lock(tid, "daemon-tick", blocking=False) as again:
        assert again


def test_scheduler_sees_tenant_ids_only_via_function(store):
    a, b = _tenant(store), _tenant(store)
    ids = store.tenants()
    assert a in ids and b in ids


def test_task_table_is_per_account(store):
    from joblander.tasks import PgTable
    t = PgTable(store)
    a, b = _tenant(store), _tenant(store)
    t.put(a, {"id": "x1", "kind": "brief", "label": "生成 brief", "status": "running", "started": 1e9 + 1})
    t.update(a, "x1", status="done", result={"path": "b.md"}, ended=2e9)
    assert t.get(a, "x1")["result"] == {"path": "b.md"}
    assert t.get(b, "x1") is None and t.all(b) == []
