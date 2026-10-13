"""可选：网关测试整套跑在 Postgres 上（GCP 形态用 Cloud SQL）。

  GW_TEST_PG_DSN=postgresql://… pytest

每个测试开始前清空网关的表；测试里写的 SQLite 路径一律换成这个连接串。
"""

from __future__ import annotations

import os
import re

import pytest

DSN = os.environ.get("GW_TEST_PG_DSN", "")


@pytest.fixture(autouse=True)
def _gateway_on_postgres(monkeypatch):
    if not DSN:
        yield
        return
    import psycopg

    from gw import db, store
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", store.SCHEMA)
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("reset role")
        for t in tables:
            c.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    real = db.connect
    opened = []

    def connect(target):                       # 测试里每个 Store 一条连接：结束时统一关掉
        conn = real(DSN)
        opened.append(conn)
        return conn
    monkeypatch.setattr(db, "connect", connect)
    yield
    for conn in opened:
        try:
            conn.close()
        except Exception:
            pass


def pytest_collection_modifyitems(config, items):
    """这几个测试用 PRAGMA database_list 取 SQLite 文件路径给命令行工具——只属于 Fly 形态。"""
    if not DSN:
        return
    import inspect
    skip = pytest.mark.skip(reason="依赖 SQLite 文件路径（Fly 形态专属）")
    for item in items:
        src = inspect.getsource(item.function) if hasattr(item, "function") else ""
        if "PRAGMA database_list" in src:
            item.add_marker(skip)
