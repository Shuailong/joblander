"""全新安装 · 空 workspace：不配任何可选集成也必须能开作战室。

2026-09-07 干净沙箱实测补的回归。此前 09-projections/tracker.json 只有
`joblander pull`（需要 Notion）会生成，而 README 明说 Notion 可选——纯本地用户
装完起服务，首页 / 作战室 / Playbook 三个页面直接 500，等于开箱即坏。
"""

import json

import pytest
from fastapi.testclient import TestClient

import joblander.notion as notion_mod
from joblander.config import Config
from joblander.onboard import onboard


@pytest.fixture
def fresh_client(tmp_path, monkeypatch):
    """只有 workspace 目录，没有投影、没有素材、没有 Notion/Gmail/search。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": []}},
                 path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    monkeypatch.setattr(notion_mod.NotionClient, "_request",
                        lambda self, *a, **k: {"results": [], "id": "created"})
    from joblander.web.app import TASKS, create_app
    TASKS.clear()
    return TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1"), ws


def test_core_pages_render_on_empty_workspace(fresh_client):
    """没有 tracker.json 就是「空战线」，不是错误。"""
    client, _ = fresh_client
    for path in ["/", "/pipeline", "/playbook", "/sourcing", "/system",
                 "/arsenal", "/offers"]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} 挂了：{r.status_code}"


def test_onboard_seeds_empty_projection(tmp_path):
    """onboard 建空投影——纯本地用户不必被指去跑需要 Notion 的 pull。"""
    ws = tmp_path / "ws"
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")

    report = onboard(cfg)

    proj = ws / "09-projections" / "tracker.json"
    assert proj.exists()
    assert json.loads(proj.read_text(encoding="utf-8")) == {"rows": []}
    assert "pull" in report and "web" in report      # 两条路都指明


def test_onboard_is_idempotent_and_keeps_pulled_rows(tmp_path):
    """重跑 onboard 不得把已拉下来的战线清空。"""
    ws = tmp_path / "ws"
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    onboard(cfg)
    proj = ws / "09-projections" / "tracker.json"
    proj.write_text(json.dumps({"rows": [{"Company": "Acme"}]}), encoding="utf-8")

    onboard(cfg)

    assert json.loads(proj.read_text(encoding="utf-8"))["rows"][0]["Company"] == "Acme"
