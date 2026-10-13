"""GCP 形态：计量服务按 X-Joblander-Tenant 认账户（调用方由 Cloud Run IAM 限定为引擎 / 任务服务）；
共享引擎后端的令牌格式与引擎一致；PgLeader 同一时刻只让一个实例领头。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from gw.meter import create_meter_app
from gw.shared import tenant_token
from gw.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "gw.sqlite"))
    s.create("a@x.com", 1.0)
    s.set_status("a@x.com", "ready", machine_id="shared", volume_id="tenant-aaaaaa")
    return s


def test_meter_identifies_account_by_tenant_header(store):
    c = TestClient(create_meter_app(store, "sk", {"m": {"input": 1, "output": 1}}, trust_tenant_header=True))
    assert c.get("/healthz").json() == {"ok": True}
    ok = c.post("/v1/events", json={"events": [{"name": "GET /sourcing", "at": time.time()}]},
                headers={"x-joblander-tenant": "tenant-aaaaaa"})
    assert ok.json() == {"ok": True, "n": 1}
    assert c.post("/v1/events", json={"events": []}).status_code == 401                    # 没指明账户
    assert c.post("/v1/events", json={"events": []},
                  headers={"x-joblander-tenant": "tenant-zzzzzz"}).status_code == 401       # 不存在的账户
    # Fly 形态的子 key 在 GCP 计量服务上不认
    assert c.post("/v1/events", json={"events": []},
                  headers={"authorization": "Bearer whatever"}).status_code == 401


def test_tenant_token_matches_engine_format():
    import importlib.util
    if importlib.util.find_spec("joblander") is None:
        pytest.skip("引擎包未安装")
    from joblander.cloud import tokens
    tok = tenant_token("tenant-aaaaaa", "k" * 40, now=1000)
    assert tokens.verify(tok, key=b"k" * 40, now=1100) == "tenant-aaaaaa"
