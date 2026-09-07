"""2026-09-07 代码 review 发现的 major 缺陷回归。

共同点：都在「测试夹具预置了产物、真实冷启动却没有」或「文档与代码各说各话」的缝里，
所以 261 个测试一条都没拦住。
"""

import json
import pathlib

import pytest
import yaml

from joblander import company as cf
from joblander import daemon as dmod
from joblander.config import Config
from joblander.scout import dedupe


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "08-events").mkdir(parents=True)
    return Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")


# ---------- 尽调档案：写读 slug 必须一致 ----------

@pytest.mark.parametrize("name", [
    "PAYCORP (SINGAPORE) PTE. LTD.",     # 半角括号：新加坡法人名 / MCF 返回的常态
    "Helios Asia（亚洲）",                # 全角括号
    "A" * 55,                            # 41-60 字符：两套 slug 的截断长度不同
    "Plain Co",
])
def test_dossier_write_and_read_agree(cfg, name):
    """写进去读不出来 = 公司页看不到调研、assess 静默零证据评估。"""
    w = cf.dossier_path(cfg, name, for_write=True)
    w.parent.mkdir(parents=True, exist_ok=True)
    w.write_text(json.dumps({"summary_md": "证据"}), encoding="utf-8")

    r = cf.dossier_path(cfg, name)
    assert r == w and r.exists()
    assert json.loads(r.read_text())["summary_md"] == "证据"


def test_dossier_falls_back_to_legacy_name(cfg):
    """存量档案是按老 slug 落的盘，不能因为改了规范就读不到。"""
    name = "PAYCORP (SINGAPORE) PTE. LTD."
    d = cfg.workspace_dir / "14-dossiers"
    d.mkdir(parents=True)
    legacy = d / f"{cf._legacy_dossier_slug(name)}.json"
    legacy.write_text(json.dumps({"summary_md": "旧档"}), encoding="utf-8")

    p = cf.dossier_path(cfg, name)
    assert p == legacy
    assert cf.dossier_path(cfg, name, for_write=True) != legacy   # 新的一律写规范名


# ---------- 示例配置的 group_exclusivity 形状 ----------

def test_dedupe_survives_example_config_shape():
    """照着 config.example 填的人，此前每次录入都 AttributeError → 500。"""
    example = yaml.safe_load(open("config.example.yaml", encoding="utf-8"))
    groups = example["policy"]["group_exclusivity"]
    rows = [{"Company": "集团公司A", "Status": "Applied"}]

    assert dedupe(rows, "全新公司", groups)["verdict"] == "new"
    assert dedupe(rows, "集团公司B", groups)["verdict"] == "group_conflict"


def test_dedupe_tolerates_bare_list_shape():
    """历史上示例写过纯列表，存量 config 不能一填就崩。"""
    rows = [{"Company": "集团公司A", "Status": "Applied"}]
    assert dedupe(rows, "集团公司B", [["集团公司A", "集团公司B"]])["verdict"] == "group_conflict"
    assert dedupe(rows, "无关公司", [["集团公司A"]])["verdict"] == "new"


# ---------- 转写收件箱 ----------

def test_transcript_watch_uses_documented_directory(cfg, monkeypatch):
    """DESIGN/MIGRATION/onboard 都写 06-transcripts，daemon 却只看 06-communites——
    W8 自动链路对除作者以外的所有人从未启动过。"""
    inbox = cfg.workspace_dir / "06-transcripts"
    inbox.mkdir(parents=True)
    (cfg.workspace_dir / "09-projections").mkdir(parents=True)
    (cfg.workspace_dir / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": [{"Company": "Acme", "notion_page_id": "p1"}]}), encoding="utf-8")
    d = dmod.Daemon(cfg)

    d.job_transcript_watch()                       # 首启：空收件箱也算已初始化
    assert d.state["transcripts_seen"] == []

    (inbox / "2026-09-07-Acme.md").write_text("面试纪要", encoding="utf-8")
    ran = {}
    monkeypatch.setattr("joblander.scribe.shadow_run",
                        lambda c, llm, f, row: ran.setdefault("file", f.name) or f)
    monkeypatch.setattr(dmod.Daemon, "_llm", lambda self, tier="pro": object())
    monkeypatch.setattr("joblander.notify.notify", lambda *a, **k: None)

    d.job_transcript_watch()

    assert ran.get("file") == "2026-09-07-Acme.md", "掉进来的第一份转写被吞了"


def test_transcript_watch_still_reads_legacy_directory(cfg):
    """作者存量在 06-communites，改规范不能把他自己的环境弄坏。"""
    (cfg.workspace_dir / "06-communites").mkdir(parents=True)
    (cfg.workspace_dir / "06-communites" / "old.md").write_text("x", encoding="utf-8")
    d = dmod.Daemon(cfg)

    d.job_transcript_watch()

    assert d.state["transcripts_seen"] == ["old.md"]


# ---------- daemon 对可选集成的容忍 ----------

def test_daemon_notion_jobs_noop_without_token(cfg, monkeypatch):
    """没配 Notion：不该每 15 分钟一条 job.failed，也不该每天 08:15 崩掉晨报。"""
    def boom(*a, **k):
        raise AssertionError("没配 Notion 时不该碰 Notion")
    monkeypatch.setattr("joblander.notion.pull_tracker_with_diff", boom)
    monkeypatch.setattr("joblander.notion.NotionClient", boom)
    monkeypatch.setattr("joblander.notify.notify", lambda *a, **k: None)
    built = {}
    monkeypatch.setattr("joblander.daily.build_daily",
                        lambda c, notion_client=None: built.setdefault(
                            "client", notion_client) or (tmp := cfg.workspace_dir / "d.md",
                                                         "# 晨报")[0:2])
    d = dmod.Daemon(cfg)

    d.job_notion_diff_pull()                       # 直接跳过，不炸
    d.state["done.morning"] = ""                   # 强制今天未出过
    monkeypatch.setattr(dmod.Daemon, "_due_daily", lambda self, *a, **k: True)
    d.job_morning_report()

    assert built["client"] is None                 # 纯本地晨报照出


def test_calendar_watch_gap_only_tick_does_not_crash(cfg, monkeypatch):
    """有排期缺口但本 tick 没有 T-24h/T-2h 场次（常态）→ 曾 UnboundLocalError，
    被记成 job.failed 污染 /system 失败计数。"""
    (cfg.workspace_dir / ".credentials").mkdir(parents=True)
    (cfg.workspace_dir / ".credentials" / "calendar_token.json").write_text("{}")
    (cfg.workspace_dir / "09-projections").mkdir(parents=True)
    (cfg.workspace_dir / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": [{"Company": "Acme", "notion_page_id": "p1",
                              "Status": "Interview Scheduled"}]}), encoding="utf-8")
    monkeypatch.setattr("joblander.calendar_sync.upcoming_events", lambda c, days=7: [])
    monkeypatch.setattr("joblander.coordinator.schedule_gaps",
                        lambda rows, events, today: [
                            {"type": "tracker_behind", "company": "Acme", "page_id": "p1",
                             "event_title": "面试", "start": "2026-09-09T10:00:00+08:00"}])
    monkeypatch.setattr("joblander.notify.notify", lambda *a, **k: None)
    d = dmod.Daemon(cfg)

    d.job_calendar_watch()          # 不抛异常即通过

    props = list((cfg.workspace_dir / "12-intake").glob("*.json"))
    assert props, "缺口提案该照常落盘"


# ---------- Notion「看起来配了其实没配」 ----------

def test_notion_configured_requires_token_and_data_source():
    """调用方过去只看 token，而 config.example 里 token 是占位符、ds_id 留空——
    照示例配置的新用户被判成「已配 Notion」，daily / pull / daemon 晨报全崩在 pull_tracker。"""
    from joblander.notion import notion_configured

    def c(n):
        return Config(raw={"workspace_dir": "/tmp/x", "notion": n} if n is not None
                      else {"workspace_dir": "/tmp/x"}, path=pathlib.Path("/tmp/c.yaml"))

    assert notion_configured(c({"token": "real", "tracker_data_source_id": "ds"})) is True
    assert notion_configured(c({"token": "ntn_xxx", "tracker_data_source_id": ""})) is False
    assert notion_configured(c({"token": "real"})) is False           # 缺 ds_id
    assert notion_configured(c({"tracker_data_source_id": "ds"})) is False
    assert notion_configured(c(None)) is False


def test_example_config_is_local_only_by_default():
    """示例配置默认必须是「没配 Notion」，否则新用户第一条命令就崩。"""
    from joblander.notion import notion_configured
    raw = yaml.safe_load(open("config.example.yaml", encoding="utf-8"))
    cfg = Config(raw=raw, path=pathlib.Path("config.example.yaml"))
    assert notion_configured(cfg) is False


def test_daily_builds_without_notion(tmp_path, monkeypatch):
    """纯本地晨报要出得来，读现成投影而不是去 pull。"""
    ws = tmp_path / "ws"
    for d in ("08-events", "09-projections", "13-daily"):
        (ws / d).mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(json.dumps({"rows": [
        {"Company": "Acme", "Status": "Applied", "notion_page_id": "p1"}]}), encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.notion.pull_tracker",
                        lambda c: (_ for _ in ()).throw(AssertionError("不该去 pull")))
    from joblander.daily import build_daily

    out, text = build_daily(cfg, notion_client=None)

    # 关键回归是「不再崩」：以前无条件 pull_tracker，纯本地用户拿不到晨报。
    # 具体列哪些行是报告自己的筛选逻辑，不在本用例范围内。
    assert out.exists() and "晨报" in text


def test_cli_reports_notion_error_as_one_line(monkeypatch, capsys):
    """`joblander pull` 没配 Notion 时给一行人话，不甩栈。"""
    from joblander.__main__ import main
    from joblander.notion import NotionError
    monkeypatch.setattr("joblander.__main__._run",
                        lambda argv=None: (_ for _ in ()).throw(
                            NotionError("config.notion 缺 token / tracker_data_source_id")))

    code = main(["pull"])

    err = capsys.readouterr().err
    assert code == 1 and err.startswith("✗ ") and "Traceback" not in err


# ---------- 失败不再静默 ----------

def test_jd_fetch_failure_is_logged_and_named(cfg, monkeypatch):
    """抓取失败此前被整段吞掉，用户只看到「缺 JD 原文」，不知道是网络挂了、
    被反爬拦了、还是链接被 SSRF 守卫拒了。"""
    monkeypatch.setattr("joblander.scout.resolve_intake_text",
                        lambda c, t, k: (_ for _ in ()).throw(
                            ValueError("拒绝抓取非公网地址：10.0.0.5")))
    row = {"Company": "Acme", "Job URL": "http://10.0.0.5/jd"}

    text, origin = cf.mine_jd(cfg, row)

    assert text == "" and "抓取失败" in origin and "非公网" in origin
    log = (cfg.workspace_dir / "08-events" / "event-log.jsonl").read_text(encoding="utf-8")
    assert "company.jd_fetch_failed" in log


# ---------- 端到端实测（真实 LLM）发现的问题 ----------

def test_notion_helper_returns_none_when_unconfigured(tmp_path, monkeypatch):
    """/api/resume/react（旗舰功能）与 /api/capability/rebuild 都走 _notion()：
    此前无条件取 cfg.raw['notion']['token']，纯本地用户只拿到 error: 'notion'。"""
    import joblander.notion as notion_mod
    from fastapi.testclient import TestClient
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    monkeypatch.setattr(notion_mod.NotionClient, "_request", lambda self, *a, **k: {})
    from joblander.web.app import TASKS, create_app
    TASKS.clear()
    app = create_app(with_daemon=False)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/").status_code == 200      # 建得起来即证明闭包内无 eager 取值
    from joblander.notion import notion_configured
    assert notion_configured(cfg) is False


def test_intake_approve_creates_row_without_notion(tmp_path):
    """纯本地批准入池：档案建了，投影也必须建行，否则公司页无从寻址、
    作战室查不到这家，而提案已归档、连重试的机会都没有。"""
    from joblander.applyops import apply_proposal
    ws = tmp_path / "ws"
    for d in ("08-events", "09-projections", "12-intake"):
        (ws / d).mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    prop = ws / "12-intake" / "lead.json"
    prop.write_text(json.dumps({"kind": "lead.intake", "lead": {
        "company": "NewCo", "position": "AI Eng", "highlight": "h",
        "urls": ["https://example.com/jd"]}}, ensure_ascii=False), encoding="utf-8")

    apply_proposal(cfg, prop, yes=True)

    rows = json.loads((ws / "09-projections" / "tracker.json").read_text())["rows"]
    assert len(rows) == 1 and rows[0]["Company"] == "NewCo"
    assert rows[0]["notion_page_id"].startswith("local-")   # 页面凭它寻址
    assert rows[0]["Job URL"] == "https://example.com/jd"
    assert cf.local_entries(cfg, "NewCo"), "公司档案也该建起来"


def test_apply_refuses_already_processed_proposal(tmp_path):
    """重放已批提案会重复入时间线、done/ 再套 done/。"""
    from joblander.applyops import apply_proposal
    ws = tmp_path / "ws"
    for d in ("08-events", "09-projections", "12-intake"):
        (ws / d).mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text('{"rows": []}', encoding="utf-8")
    cfg = Config(raw={"workspace_dir": str(ws)}, path=tmp_path / "c.yaml")
    done = ws / "12-intake" / "done"
    done.mkdir()
    old = done / "lead.json"
    old.write_text(json.dumps({"kind": "lead.intake", "approved": True,
                               "lead": {"company": "NewCo"}}, ensure_ascii=False),
                   encoding="utf-8")

    with pytest.raises(ValueError, match="已处理过"):
        apply_proposal(cfg, old, yes=True)

    assert not (done / "done").exists()


@pytest.mark.parametrize("section,heading", [
    ("education", "<h2>Education</h2>"),
    ("skills", "Technical Skills"),
    ("summary", "<h2>Summary</h2>"),
])
def test_resume_omits_headings_for_empty_sections(section, heading):
    """空段落照出小标题：简历与 PDF 上留一个光秃秃的 Education（v2 里还夹在中间）。"""
    from joblander.resume_agent import _render_html
    content = {"tagline": "AI Engineer", "summary": ["S"],
               "experience": [{"company": "C", "position": "P", "when": "W",
                               "note": "", "bullets": ["b"]}],
               "skills": [{"label": "L", "value": "V"}],
               "education": [{"degree": "PhD", "institution": "U", "when": "2020", "sub": ""}],
               "publications": [], "service": ""}
    prof = {"name": "Alex Doe", "contact": []}

    assert heading in _render_html(content, prof)
    assert heading not in _render_html(dict(content, **{section: []}), prof)
