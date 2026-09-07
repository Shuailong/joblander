"""F3 playbook 回写 / F2 diff / U4 amend / daemon 调度判定 —— 全合成。"""

import json

import pytest
import yaml

from joblander.config import Config
from joblander.notion import diff_rows
from joblander.playbook import apply_updates, load, suggest_status


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    playbook = [
        {"id": "P1", "pattern": "tenure", "status": "improving",
         "engagements": [{"date": "2026-08-01", "company_ref": "A", "outcome": "miss"}]},
        {"id": "P2", "pattern": "numbers", "status": "solid", "engagements": []},
    ]
    (ws / "03-materials" / "playbook.yaml").write_text(
        yaml.safe_dump(playbook, allow_unicode=True), encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")


def test_apply_updates_appends_and_escalates(cfg):
    r = apply_updates(cfg, [{"id": "P1", "outcome": "miss", "note": "again"}],
                      company="B", date="2026-08-07")
    assert r["applied"] == ["P1"]
    assert any("needs_work" in a for a in r["alerts"])          # 连续 2 miss → 恶化升级
    entries = {e["id"]: e for e in load(cfg)}
    assert entries["P1"]["status"] == "needs_work"
    assert len(entries["P1"]["engagements"]) == 2


def test_apply_updates_idempotent_and_unknown(cfg):
    u = [{"id": "P1", "outcome": "hit", "note": "x"}]
    apply_updates(cfg, u, company="C", date="2026-08-07")
    r2 = apply_updates(cfg, u, company="C", date="2026-08-07")   # 同日同司同果
    assert r2["applied"] == []
    r3 = apply_updates(cfg, [{"id": "P9", "outcome": "hit"}], company="C")
    assert r3["unknown_ids"] == ["P9"]


def test_improvement_is_suggestion_not_overwrite(cfg):
    for d in ("01", "02", "03"):
        apply_updates(cfg, [{"id": "P1", "outcome": "hit"}], company=f"D{d}",
                      date=f"2026-08-{d}")
    e = {x["id"]: x for x in load(cfg)}["P1"]
    assert e["status"] == "improving"            # 人工值不被自动洗好
    assert e.get("_suggested_status") == "solid"  # 只挂建议


def test_suggest_status_rules():
    assert suggest_status({"status": "solid", "engagements": [
        {"outcome": "miss"}, {"outcome": "miss"}]}) == "needs_work"
    assert suggest_status({"status": "watch", "engagements": [
        {"outcome": "hit"}, {"outcome": "hit"}, {"outcome": "hit"}]}) == "solid"


def test_diff_rows_field_add_remove():
    old = [{"notion_page_id": "1", "Company": "A", "Status": "Applied"},
           {"notion_page_id": "2", "Company": "B", "Status": "Added"}]
    new = [{"notion_page_id": "1", "Company": "A", "Status": "Interview Scheduled"},
           {"notion_page_id": "3", "Company": "C", "Status": "Added"}]
    kinds = {(c["kind"], c.get("field")) for c in diff_rows(old, new)}
    assert ("field.changed", "Status") in kinds
    assert ("row.added", None) in kinds
    assert ("row.removed", None) in kinds


def test_amend_proposal_scribe(tmp_path):
    from joblander.applyops import amend_proposal
    ws = tmp_path / "ws"; (ws / "11-shadow").mkdir(parents=True)
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    pf = ws / "11-shadow" / "p.json"     # 提案只认 11-shadow / 12-intake（路径夹紧）
    pf.write_text(json.dumps({"field_diffs": {"Status": "Terminated", "Highlight": "x"},
                              "notion_page_id": "1"}), encoding="utf-8")
    r = amend_proposal(cfg, pf, {"Status": "Interview Completed", "Highlight": "x"})
    assert r["edited"] == ["Status"]
    data = json.loads(pf.read_text())
    assert data["field_diffs"]["Status"] == "Interview Completed"
    assert data["human_edits"] == ["Status"]


def test_daemon_due_logic(tmp_path, monkeypatch):
    from joblander import daemon as dmod
    ws = tmp_path / "ws"; (ws / "08-events").mkdir(parents=True)
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    d = dmod.Daemon(cfg)

    class FakeDT:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 8, 9, 20, 5, tzinfo=tz)   # 周日 20:05
        fromisoformat = staticmethod(__import__("datetime").datetime.fromisoformat)
    monkeypatch.setattr(dmod, "datetime", FakeDT)

    assert d._due_interval("x", 30) is True
    assert d._due_interval("x", 30) is False                 # 间隔内不重复
    assert d._due_daily("m", 8, 15) is True
    assert d._due_daily("m", 8, 15) is False                 # 当日只跑一次
    assert d._due_daily("w", 20, 0, weekday=6) is True       # 周日 20:00 后
    assert d._due_daily("w2", 20, 0, weekday=2) is False     # 非周三
