"""Weekly / Offer / Consistency / Onboard / Researcher-helpers 单测 —— 全合成。"""

import json

import pytest
import yaml

from joblander.config import Config
from joblander.offer import compare_offers, offer_matrix_md
from joblander.weekly import build_weekly, funnel_stats, playbook_health, priority_proposal

POLICY = {
    "quote_tc_sgd": 250000,
    "fx": {"SGD": 1.0, "RMB": 0.186},
    "equity_discount_factors": {"light": 1.0, "medium": 0.5, "heavy": 0.0},
}

ROWS = [
    {"Company": "A", "Status": "Interview Scheduled", "Priority": "High",
     "Follow-up Reminder": "2026-08-12"},
    {"Company": "B", "Status": "Applied", "Priority": "High"},          # High 无 follow-up
    {"Company": "C", "Status": "Added"},                                # 入池未评估
    {"Company": "D", "Status": "Terminated"},
]


def test_funnel_stats():
    f = funnel_stats(ROWS)
    assert f["total"] == 4 and f["active"] == 3 and f["terminal"] == 1


def test_priority_signals():
    sig = "\n".join(priority_proposal(ROWS))
    assert "High 无 follow-up：B" in sig
    assert "入池未评估：C" in sig
    assert "只剩 1 场" in sig


def test_playbook_health_consecutive_miss(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    playbook = [
        {"id": "P1", "pattern": "x", "status": "needs_work", "engagements": [
            {"date": "2026-08-01", "outcome": "hit"},
            {"date": "2026-08-02", "outcome": "miss"},
            {"date": "2026-08-03", "outcome": "miss"}]},
        {"id": "P2", "pattern": "y", "status": "solid", "engagements": [
            {"date": "2026-08-01", "outcome": "miss"},
            {"date": "2026-08-04", "outcome": "hit"}]},
    ]
    (ws / "03-materials" / "playbook.yaml").write_text(
        yaml.safe_dump(playbook, allow_unicode=True), encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    h = {x["id"]: x for x in playbook_health(cfg)}
    assert h["P1"]["consecutive_miss"] == 2 and h["P1"]["alert"] is True
    assert h["P2"]["consecutive_miss"] == 0 and h["P2"]["alert"] is False


def test_compare_offers_discount_ordering():
    offers = [
        {"name": "CashCo", "base_monthly": 18000, "bonus_months": 2,
         "bonus_guaranteed": True},                                     # 252K 全现金
        {"name": "PaperCo", "base_monthly": 15000, "bonus_months": 0,
         "equity_face_annual": 90000, "equity_tier": "heavy"},          # 面值 270K 折价 180K
    ]
    ranked = compare_offers(POLICY, offers)
    assert ranked[0]["name"] == "CashCo"                # 折价口径下现金赢
    assert ranked[1]["tc_face_sgd"] == 270000           # 面值口径 PaperCo 更高
    md = offer_matrix_md(POLICY, offers)
    assert "报价按面值、比较按折价" in md and "CashCo" in md


def test_audit_materials_rules_layer(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    (ws / "03-materials" / "resume.md").write_text("built ProjectX end to end", encoding="utf-8")
    (ws / "03-materials" / "clean.md").write_text("built a routing system", encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws), "sentinel": {"rules": [
        {"id": "codename", "type": "pattern", "action": "block", "patterns": ["ProjectX"]}]}},
        path=tmp_path / "c.yaml")
    from joblander.consistency import audit_materials
    out, text = audit_materials(cfg)
    assert "resume.md" in text and "codename" in text
    assert "clean.md" not in text
    assert out.exists()


def test_onboard_scaffold(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    from joblander.onboard import onboard
    report = onboard(cfg)
    assert "⬜ policy" in report and "✅ workspace_dir" in report
    assert (ws / "10-briefs").exists() and (ws / "03-materials" / "profile-index.md").exists()


def test_weekly_is_user_facing(tmp_path):
    """周报面向求职者：战果按作战日期、下周的仗置顶、复盘扫纪要——无系统日志、无代号。"""
    import json as _json
    from datetime import datetime, timedelta, timezone
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(sgt)
    today = now.strftime("%Y-%m-%d")
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(_json.dumps({"rows": [
        {"Company": "Acme", "notion_page_id": "p1", "Status": "Interview Scheduled",
         "Priority": "High", "Follow-up Reminder": "2099-08-12",
         "Next Steps": "R2 系统设计"}]}), encoding="utf-8")
    (ws / "03-materials").mkdir()
    (ws / "03-materials" / "playbook.yaml").write_text(yaml.safe_dump([
        {"id": "P1", "pattern": "band 询问", "status": "needs_work",
         "engagements": [{"date": "2026-08-01", "outcome": "miss"},
                         {"date": "2026-08-05", "outcome": "miss"}]}],
        allow_unicode=True), encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    from joblander.company import set_review, timeline_add
    e = timeline_add(cfg, "Acme", kind="interview", title="R1 面试/Ann",
                     date=today, content_md="问了 RAG 架构，答得顺；band 没敢问",
                     author="ai", source="scribe")
    set_review(cfg, "Acme", entry_id=e["id"], text="下次先问 band")

    _, text = build_weekly(cfg)          # llm=None：复盘段走纪要清单回退
    assert "本周战果" in text and f"🎤 {today[5:]}｜Acme：R1 面试/Ann" in text
    assert "下周的仗与备战" in text and "2099-08-12" in text and "R2 系统设计" in text
    assert "日历缺事件" in text          # tracker 有排面、日历没有 → 缺口标注
    assert "本周复盘提炼（来自 1 份纪要）" in text
    assert "下周三件事（面试之外）" in text
    assert "参考信号" in text and "band 询问" in text and "连续 2 miss" in text
    assert "系统活动" not in text and "W11" not in text and "W15" not in text

    # 我的手记：他手写的段在周报重生成后必须原样保留
    from joblander.daily import NOTES_HEADER, save_notes
    save_notes(cfg, f"{today}-weekly.md", "这周最大的收获是把 band 话术练熟了。")
    _, text2 = build_weekly(cfg)
    assert "band 话术练熟" in text2 and f"## {NOTES_HEADER}" in text2
    assert "本周战果" in text2


def test_schedule_gaps_bidirectional():
    from joblander.coordinator import schedule_gaps
    rows = [{"Company": "Acme AI", "notion_page_id": "p1",
             "Status": "Interview Scheduled", "Follow-up Reminder": "2026-08-12"},
            {"Company": "Beta", "notion_page_id": "p2", "Status": "Applied"}]
    cal = [{"title": "Beta onsite interview", "start": "2026-08-11T14:00:00+08:00",
            "kind": "interview"}]
    gaps = schedule_gaps(rows, cal, "2026-08-08")
    assert {g["type"] for g in gaps} == {"missing_calendar", "tracker_behind"}
    assert next(g for g in gaps if g["type"] == "missing_calendar")["company"] == "Acme AI"
    assert next(g for g in gaps if g["type"] == "tracker_behind")["company"] == "Beta"


def test_calendar_event_proposal_flow(tmp_path, monkeypatch):
    """排期缺口提案：缺时间拒绝执行；改后批 → 建日历事件（确认制）。"""
    import json as _json
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = Config(raw={"workspace_dir": str(ws), "notion": {"token": "fake"}},
                 path=tmp_path / "c.yaml")
    pf = ws / "gap.json"
    pf.write_text(_json.dumps({"kind": "calendar.event", "company": "Acme",
                               "title": "面试：Acme", "date": "", "time": "",
                               "duration_min": 60, "approved": None}))
    from joblander.applyops import amend_proposal, apply_proposal
    with pytest.raises(ValueError):
        apply_proposal(cfg, pf, yes=True)

    created = {}
    monkeypatch.setattr("joblander.calendar_sync.create_event",
                        lambda cfg_, title, s, e, description="", confirmed=False:
                        created.update({"title": title, "start": s,
                                        "confirmed": confirmed}) or {"id": "evt1"})
    amend_proposal(cfg, pf, {"date": "2026-08-12", "time": "14:00"})
    result = apply_proposal(cfg, pf, yes=True)
    assert result["calendar"]["id"] == "evt1"
    assert created["start"] == "2026-08-12T14:00:00+08:00" and created["confirmed"]
    assert _json.loads(pf.read_text())["approved"] is True
