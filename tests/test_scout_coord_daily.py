"""Scout / Coordinator / Daily 单测 —— 全合成，公开可跑。"""

import json

import pytest

from joblander.config import Config
from joblander.coordinator import check_candidate_slot, pick_slot
from joblander.scout import dedupe

ROWS = [
    {"Company": "Shopee", "Status": "Terminated"},
    {"Company": "Sea Group（非 Shopee 线）", "Status": "Applied"},
    {"Company": "Acme AI", "Status": "Interview Scheduled"},
]
GROUPS = [{"group": "Sea Group", "members": ["Shopee", "Sea Group", "Garena"],
           "rule": "同集团同时只受理一个申请"}]


def test_dedupe_duplicate():
    assert dedupe(ROWS, "acme ai", GROUPS)["verdict"] == "duplicate"


def test_dedupe_group_conflict():
    v = dedupe(ROWS, "Garena", GROUPS)
    assert v["verdict"] == "group_conflict"
    assert "Sea Group（非 Shopee 线）" in v["active_members"]   # Shopee 已终态不算


def test_dedupe_new_and_unknown():
    assert dedupe(ROWS, "Totally New Co", GROUPS)["verdict"] == "new"
    assert dedupe(ROWS, None, GROUPS)["verdict"] == "unknown_company"


def test_intake_noise_gate(tmp_path):
    """无公司无岗位 = 噪音：不进审批队列，只记 lead.discarded 事件。"""
    from joblander.llm import MockLLM
    from joblander.scout import intake
    cfg = Config(raw={"workspace_dir": str(tmp_path)}, path=tmp_path / "c.yaml")
    llm = MockLLM([json.dumps({"company": "", "position": "", "highlight": ""})])
    out = intake(cfg, llm, "Weekly newsletter: 10 tips for interviews", "gmail")
    assert out is None
    assert not (tmp_path / "12-intake").exists()
    log = (tmp_path / "08-events" / "event-log.jsonl").read_text()
    assert "lead.discarded" in log


def test_intake_not_job_discarded_even_with_company(tmp_path):
    """实战教训：发件方是公司 ≠ 工作机会——category=not_job 必须被丢弃。"""
    from joblander.llm import MockLLM
    from joblander.scout import intake
    cfg = Config(raw={"workspace_dir": str(tmp_path)}, path=tmp_path / "c.yaml")
    llm = MockLLM([json.dumps({"category": "not_job", "company": "FinApp Co",
                               "position": None, "highlight": "交易通知"})])
    out = intake(cfg, llm, "Your transaction details are available", "gmail")
    assert out is None
    log = (tmp_path / "08-events" / "event-log.jsonl").read_text()
    assert '"not_job"' in log and "FinApp Co" in log


def _cfg_with_rows(tmp_path):
    proj = tmp_path / "09-projections"
    proj.mkdir(parents=True)
    (proj / "tracker.json").write_text(json.dumps({"rows": [
        {"Company": "Acme AI", "notion_page_id": "aaa111", "Status": "Applied"}]}))
    return Config(raw={"workspace_dir": str(tmp_path)}, path=tmp_path / "c.yaml")


def test_intake_exclude_words_apply_to_all_channels(tmp_path):
    """排除词（如 manager——IC 不看管理岗）对 gmail/贴入渠道同样生效，不只 MCF。"""
    from joblander.llm import MockLLM
    from joblander.scout import intake
    cfg = _cfg_with_rows(tmp_path)
    prefs_p = tmp_path / "02-targets"
    prefs_p.mkdir(parents=True)
    (prefs_p / "sourcing-prefs.yaml").write_text("exclude:\n- manager\n", encoding="utf-8")
    llm = MockLLM([json.dumps({"category": "job_lead", "company": "NewCorp",
                               "position": "Engineering Manager, AI Platform"})])
    assert intake(cfg, llm, "Great EM role!", "linkedin") is None
    log = (tmp_path / "08-events" / "event-log.jsonl").read_text()
    assert "exclude_keyword" in log


def test_intake_followup_becomes_company_update(tmp_path):
    """已有战线的跟进（面试邀约/JD 补充）→ 该公司的更新提案，不进待入池。"""
    from joblander.llm import MockLLM
    from joblander.scout import intake
    cfg = _cfg_with_rows(tmp_path)
    llm = MockLLM([json.dumps({
        "category": "followup", "company": "Acme AI", "position": "MLE",
        "comp_mentions": ["band 8-10k"], "urls": [],
        "highlight": "约二面，给了两个时段",
        "suggested_next_step": "回复确认周四 14:00"})])
    out = intake(cfg, llm, "Hi, we'd like to schedule round 2...", "email")
    assert "-followup" in out.name
    p = json.loads(out.read_text(encoding="utf-8"))
    assert p["origin"] == "scout.followup" and p["notion_page_id"] == "aaa111"
    assert p["field_diffs"]["Next Steps"] == "回复确认周四 14:00"
    assert "band 8-10k" in p["body_entry"] and p["approved"] is None


def test_intake_duplicate_lead_converts_to_update(tmp_path):
    """自称新机会但查重命中已有行 → 同样转更新提案（不再产重复入池卡）。"""
    from joblander.llm import MockLLM
    from joblander.scout import intake
    cfg = _cfg_with_rows(tmp_path)
    llm = MockLLM([json.dumps({"category": "job_lead", "company": "Acme AI",
                               "position": "Senior MLE", "highlight": "同岗位再推"})])
    out = intake(cfg, llm, "Exciting role at Acme AI!", "linkedin")
    assert "-followup" in out.name
    assert json.loads(out.read_text(encoding="utf-8"))["company"] == "Acme AI"


EXISTING = [
    {"start": "2026-08-13T16:00", "end": "2026-08-13T17:00", "kind": "interview", "title": "A面"},
]


def test_slot_overlap_and_buffer():
    v = check_candidate_slot(EXISTING, "2026-08-13T16:30", "2026-08-13T17:30")
    assert any("重叠" in x for x in v)
    v = check_candidate_slot(EXISTING, "2026-08-13T17:10", "2026-08-13T18:00")
    assert any("缓冲不足" in x for x in v)


def test_slot_hard_per_day_limit():
    two = EXISTING + [{"start": "2026-08-13T10:00", "end": "2026-08-13T11:00",
                       "kind": "tech", "title": "B面"}]
    v = check_candidate_slot(two, "2026-08-13T13:00", "2026-08-13T14:00", kind="interview")
    assert any("同日硬面" in x for x in v)


def test_tech_prep_gap():
    v = check_candidate_slot(EXISTING, "2026-08-13T18:30", "2026-08-13T19:30", kind="tech")
    assert any("保护块不足" in x for x in v)


def test_pick_slot_orders_by_violations():
    ranked = pick_slot(EXISTING, [("2026-08-13T16:30", "2026-08-13T17:30"),
                                  ("2026-08-14T10:00", "2026-08-14T11:00")])
    assert ranked[0]["start"].startswith("2026-08-14")
    assert ranked[0]["ok"] is True


def test_daily_sections(tmp_path):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "11-shadow").mkdir(parents=True)
    rows = [
        {"Company": "OverdueCo", "Status": "Applied", "Priority": "High",
         "Next Steps": "nudge", "Follow-up Reminder": "2026-08-01"},
        {"Company": "TodayCo", "Status": "Screening Called",
         "Next Steps": "call", "Follow-up Reminder": "2026-08-07"},
        {"Company": "DoneCo", "Status": "Terminated", "Follow-up Reminder": "2026-08-01"},
    ]
    (ws / "09-projections" / "tracker.json").write_text(json.dumps({"rows": rows}))
    (ws / "11-shadow" / "p.json").write_text(json.dumps({"company": "X", "approved": None}))
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")

    from joblander.daily import build_daily
    out, text = build_daily(cfg, today="2026-08-07")
    assert "逾期 follow-up" in text and "OverdueCo" in text
    assert "今日到期" in text and "TodayCo" in text
    assert "DoneCo" not in text                    # 终态行不进 follow-up
    assert "待你审批（1）" in text
    assert out.exists()

    # 三段共存：日记与手记各归其段，晨报重生成不得吃掉它们
    from joblander.daily import (DIARY_HEADER, NOTES_HEADER, daily_path,
                                 read_section, save_notes, upsert_section)
    upsert_section(daily_path(cfg, "2026-08-07"), DIARY_HEADER,
                   "### 2026-08-07\n【进展】面了 Acme", title="# 日报 · 2026-08-07")
    save_notes(cfg, "2026-08-07.md", "今天状态不错，别慌。")
    _, text2 = build_daily(cfg, today="2026-08-07")
    assert "面了 Acme" in text2 and "别慌" in text2 and "OverdueCo" in text2
    assert text2.index("晨报") < text2.index("今日日记") < text2.index("我的手记")
    assert read_section(daily_path(cfg, "2026-08-07"), NOTES_HEADER) == "今天状态不错，别慌。"
    import pytest as _pt
    with _pt.raises(ValueError):
        save_notes(cfg, "../evil.md", "x")


def test_resolve_intake_text_links(tmp_path, monkeypatch):
    """贴入链接自动解析：MCF 走结构化 API、通用链接抓正文、抓不到明说要原文。"""
    from joblander.scout import resolve_intake_text
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")

    text, src = resolve_intake_text(cfg, "普通来信原文，不是链接", "whatsapp")
    assert (text, src) == ("普通来信原文，不是链接", "whatsapp")   # 非链接原样通过

    monkeypatch.setattr("joblander.sourcing.mcf_job_detail", lambda uuid, timeout=20: {
        "title": "AI Engineer", "postedCompany": {"name": "ACME PTE. LTD."},
        "salary": {"minimum": 10000, "maximum": 16000, "type": {"salaryType": "Monthly"}},
        "minimumYearsExperience": 5, "skills": [{"skill": "Python"}, {"skill": "LLM"}],
        "description": "<p>Build agents</p>"})
    url = "https://www.mycareersfuture.gov.sg/job/it/ai-engineer-acme-" + "a" * 32
    text, src = resolve_intake_text(cfg, url, "paste")
    assert src == "mcf" and "AI Engineer" in text and "10000-16000" in text
    assert "Python、LLM" in text and "Build agents" in text and url in text

    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Job description body " * 30)
    text, src = resolve_intake_text(cfg, "https://www.linkedin.com/jobs/view/123", "paste")
    assert src == "linkedin" and "Job description body" in text and "原始链接" in text

    monkeypatch.setattr("joblander.researcher.fetch_url", lambda u, timeout=20: "")
    with pytest.raises(ValueError, match="贴进来"):
        resolve_intake_text(cfg, "https://example.com/jd", "paste")


def test_calendar_kind_tagging_keywords_and_company(tmp_path, monkeypatch):
    """日历打标双腿：标题关键词或活跃公司名命中 → interview；私人日程 → block。
    打标在源头统一——指挥中心显示、T-24h 弹药、排期对账吃同一个判定。"""
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(json.dumps(
        {"rows": [{"Company": "Nimbus（深圳）", "Status": "Interview Scheduled"}]}))
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    from joblander import calendar_sync
    monkeypatch.setattr(calendar_sync, "_api", lambda *a, **k: {"items": [
        {"summary": "Acme HackerRank Interview", "start": {"dateTime": "x"}, "end": {}},
        {"summary": "Chat with Kai @ Nimbus", "start": {"dateTime": "x"}, "end": {}},
        {"summary": "Hiking w/ friends", "start": {"dateTime": "x"}, "end": {}}]})
    kinds = {e["title"]: e["kind"] for e in calendar_sync.upcoming_events(cfg)}
    assert kinds["Acme HackerRank Interview"] == "interview"   # 关键词腿
    assert kinds["Chat with Kai @ Nimbus"] == "interview"        # 公司名腿（短名去括号）
    assert kinds["Hiking w/ friends"] == "block"


def test_diary_draft_from_battle_events_only(tmp_path):
    """日记素材=各公司今日战线事件；评估等系统数据更新不进；无战线不出草稿。"""
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(json.dumps({"rows": [
        {"Company": "Acme", "Status": "Interview Scheduled", "Priority": "High",
         "Next Steps": "thanks note", "Follow-up Reminder": "2026-08-08"}]}))
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    from joblander import company as cf
    cf.timeline_add(cfg, "Acme", kind="interview", title="R2/Ann",
                    content_md="聊了 agent 架构", date="2026-08-07", author="human")
    cf.timeline_add(cfg, "Acme", kind="assessment", title="评估匹配",
                    content_md="score 4", date="2026-08-07", author="ai")
    cf.timeline_add(cfg, "Beta", kind="call", title="猎头通话",
                    content_md="band 沟通", date="2026-08-06", author="human")

    from joblander.diary import build_diary_draft, today_battle_events
    battles = today_battle_events(cfg, "2026-08-07")
    assert [b["kind"] for b in battles] == ["interview"]      # 评估不算，昨天的不算

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            assert "聊了 agent 架构" in prompt and "score 4" not in prompt
            assert "thanks note" in prompt                    # 明日 follow-up 进素材
            return "### 2026-08-07\n【进展】Acme R2 聊了 agent 架构"
    out = build_diary_draft(cfg, L(), today="2026-08-07")
    prop = json.loads(out.read_text())
    assert prop["kind"] == "diary.entry" and prop["date"] == "2026-08-07"

    assert build_diary_draft(cfg, L(), today="2026-08-09") is None   # 无战线日不出稿


def test_daemon_state_single_writer(tmp_path):
    """web 手动刷新写 state 走 daemon 内存——daemon tick 的整文件快照不再回滚它。"""
    ws = tmp_path / "ws"
    (ws / "08-events").mkdir(parents=True)
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    from joblander.daemon import Daemon
    d = Daemon(cfg)                       # 不 start——只用 state 机制
    d.state["last.gmail_scan"] = "OLD"
    d._save_state()
    d.patch_state({"last.notion_pull": "NEW"})    # = web 手动刷新
    d._save_state()                                # = 下一次 daemon tick 落盘
    data = json.loads((ws / "08-events" / "daemon-state.json").read_text())
    assert data["last.notion_pull"] == "NEW"      # 手动戳存活
    assert data["last.gmail_scan"] == "OLD"       # daemon 自己的键不丢

def test_suggest_slots_full_flow():
    """W6 排期参谋：抽取(LLM) → 规则对照 → 推荐 + 草稿；报告含违例与草稿。"""
    from joblander.coordinator import format_slot_report, suggest_slots
    from joblander.llm import MockLLM
    llm = MockLLM([
        json.dumps({"slots": [
            {"start": "2026-08-13T16:30", "end": "2026-08-13T17:30", "label": "Wed 4:30pm"},
            {"start": "2026-08-14T10:00", "end": "2026-08-14T11:00", "label": "Thu 10am"}],
            "duration_min": 60, "language": "en", "sender": "Jane", "notes": ""}),
        "Hi Jane, Thursday 10am SGT works great for me. Looking forward to it!",
    ])
    out = suggest_slots(None, llm, "Would Wed 4:30pm or Thu 10am work?",
                        company="Acme AI", cal_events=EXISTING)
    assert out["best"]["start"] == "2026-08-14T10:00"          # 冲突的排后，干净的当选
    assert not out["slots"][0]["violations"] and out["slots"][1]["violations"]
    assert "Thursday" in out["draft"]
    report = format_slot_report(out)
    assert "✅ 可约" in report and "⚠️" in report and "你来发" in report
    assert "Thu 10am" in report                                 # label 跟着排序走


def test_suggest_slots_no_extractable_time():
    """抽不到完整时段：不编造，notes 透传，报告如实说。"""
    from joblander.coordinator import format_slot_report, suggest_slots
    from joblander.llm import MockLLM
    llm = MockLLM([json.dumps({"slots": [], "notes": "只说了下周，没给钟点"})])
    out = suggest_slots(None, llm, "Let's chat next week sometime", cal_events=[])
    assert out["slots"] == [] and out["best"] is None and out["draft"] == ""
    assert "没给钟点" in format_slot_report(out)
