"""网页设置向导：新用户不碰 config.yaml、不手建文件也能把系统喂到能用。"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from joblander import wizard
from joblander.config import Config, load_config
from joblander.llm import MockLLM

RESUME = ("张三  zhangsan@example.com  linkedin.com/in/zhangsan\n"
          "Acme Pay · Senior Engineer · 2021-2025\n"
          "- 主导支付路由重构，P99 延迟从 800ms 降到 120ms\n"
          "- 带 4 人小组完成对账系统迁移，月均差错从 37 单降到 2 单\n" * 3)

LLM_OUT = json.dumps({
    "profile": {"name": "张三", "contact": [
        {"text": "zhangsan@example.com", "href": "mailto:zhangsan@example.com"},
        {"text": "", "href": "x"}]},
    "sections": [
        {"title": "Acme Pay · Senior Engineer · 2021–2025", "items": [
            {"headline": "支付路由重构，P99 800ms → 120ms", "detail": "主导重构"},
            {"headline": "对账系统迁移，月均差错 37 → 2 单", "detail": ""}]},
        {"title": "空段", "items": []}]}, ensure_ascii=False)


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("# 手写注释\nworkspace_dir: " + str(tmp_path / "ws") + "\n"
                 "sentinel:\n  rules:\n  - {id: keep-me, type: pattern, patterns: [X]}\n",
                 encoding="utf-8")
    return load_config(p)


def test_bootstrap_writes_numbered_bank_and_profile(cfg):
    out = wizard.bootstrap_from_resume(cfg, MockLLM([LLM_OUT]), RESUME)
    assert out == {"items": 2, "profile": True}
    bank = wizard.bank_path(cfg).read_text(encoding="utf-8")
    # 编号全库连续：教练归档 / brief 引用 / 幻觉编号检查都靠 ### A<n>.
    assert "### A1. 支付路由重构" in bank and "### A2. 对账系统迁移" in bank
    assert "空段" not in bank
    assert "使用注意" in bank                 # 红线段在，弹药库页按 internal 隐藏
    prof = json.loads(wizard.profile_path(cfg).read_text(encoding="utf-8"))
    assert prof["name"] == "张三" and len(prof["contact"]) == 1


def test_bootstrap_never_overwrites_existing_bank(cfg):
    wizard.bank_path(cfg).parent.mkdir(parents=True)
    wizard.bank_path(cfg).write_text("## 我核对过的\n### A1. x\n", encoding="utf-8")
    llm = MockLLM([LLM_OUT])
    with pytest.raises(ValueError, match="已经有内容"):
        wizard.bootstrap_from_resume(cfg, llm, RESUME)
    assert llm.calls == []                    # 拒在花钱之前


def test_bootstrap_rejects_scanned_resume(cfg):
    with pytest.raises(ValueError, match="扫描版"):
        wizard.bootstrap_from_resume(cfg, MockLLM([]), "   张三  ")


def test_save_basics_writes_policy_and_redlines(cfg):
    wizard.save_basics(cfg, 200000, "usd", ["ProjectX", "绩效 A+"])
    raw = yaml.safe_load(cfg.path.read_text(encoding="utf-8"))
    assert raw["policy"]["quote_tc_sgd"] == round(200000 * wizard.DEFAULT_FX["USD"])
    assert raw["policy"]["fx"]["SGD"] == 1.0           # Analyst 硬依赖
    ids = [r["id"] for r in raw["sentinel"]["rules"]]
    assert ids == ["keep-me", "wizard-redlines"]       # 手写规则不丢
    from joblander.sentinel import Sentinel
    assert Sentinel.from_config(cfg).check("我拿过 绩效 A+").action.value == "block"
    assert cfg.path.with_name("config.yaml.bak").read_text(encoding="utf-8").startswith("# 手写注释")
    # 再存一次：红线规则替换而不是叠加；清空红线词 = 删掉这条规则
    wizard.save_basics(cfg, 200000, "SGD", [])
    assert [r["id"] for r in cfg.sentinel_rules] == ["keep-me"]


def test_save_basics_validates(cfg):
    with pytest.raises(ValueError, match="币种"):
        wizard.save_basics(cfg, 1, "XYZ", [])
    with pytest.raises(ValueError, match="正数"):
        wizard.save_basics(cfg, 0, "SGD", [])


def test_status_done_needs_bank_profile_policy(cfg):
    assert wizard.needs_setup(cfg)
    wizard.bootstrap_from_resume(cfg, MockLLM([LLM_OUT]), RESUME)
    assert wizard.needs_setup(cfg)
    wizard.save_basics(cfg, 1, "SGD", [])
    assert wizard.status(cfg)["done"] and not wizard.needs_setup(cfg)


def test_web_flow_redirect_upload_basics_skip(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    monkeypatch.setenv("JOBLANDER_TASKS_SYNC", "1")
    monkeypatch.setattr("joblander.llm.from_config", lambda c, tier="pro": MockLLM([LLM_OUT]))
    from joblander.web.app import TASKS, create_app
    TASKS.clear()
    client = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1")

    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert "上传一份旧简历" in client.get("/setup").text

    bad = client.post("/api/setup/resume", files={"file": ("cv.exe", b"x")})
    assert bad.status_code == 400
    r = client.post("/api/setup/resume",
                    files={"file": ("cv.txt", RESUME.encode(), "text/plain")})
    assert r.status_code == 200 and r.json()["task"]
    assert TASKS[r.json()["task"]]["status"] == "done"
    assert wizard.status(cfg)["bank"]

    r = client.post("/api/setup/basics", data={"target_tc": "250000", "currency": "SGD",
                                               "redlines": "ProjectX\n\n"})
    assert r.status_code == 200
    assert "ProjectX" in client.get("/setup").text      # 回显的是原词，不是转义后的正则
    assert client.get("/", follow_redirects=False).status_code == 200


def test_skip_stops_redirect(cfg, monkeypatch):
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    from joblander.web.app import create_app
    client = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1")
    assert client.post("/api/setup/skip").status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 200


def test_concurrent_bootstrap_spends_once(cfg, monkeypatch):
    """按钮连点：第二单在花钱之前就被拒（云端实测出过 20 秒内连跑 3 次、后者覆盖前者）。"""
    llm = MockLLM([LLM_OUT])
    assert wizard._BOOTSTRAP_LOCK.acquire(blocking=False)      # 模拟第一单还在跑
    try:
        with pytest.raises(ValueError, match="正在生成中"):
            wizard.bootstrap_from_resume(cfg, llm, RESUME)
        monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
        from joblander.web.app import create_app
        client = TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1")
        r = client.post("/api/setup/resume",
                        files={"file": ("cv.txt", RESUME.encode(), "text/plain")})
        assert r.status_code == 409
    finally:
        wizard._BOOTSTRAP_LOCK.release()
    assert llm.calls == []
    wizard.bootstrap_from_resume(cfg, llm, RESUME)              # 锁释放后照常
    assert len(llm.calls) == 1
