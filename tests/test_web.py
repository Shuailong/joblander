"""Web 层集成测试 —— TestClient + 合成 workspace，公开可跑（不触网：Notion 请求全部打桩）。"""

import json

import pytest
import yaml
from fastapi.testclient import TestClient

import joblander.notion as notion_mod
from joblander.config import Config

ROWS = [
    {"notion_page_id": "aaa111", "url": "https://notion.so/aaa111", "Company": "Acme AI",
     "Position": "Engineer", "Status": "Interview Scheduled", "Priority": "High",
     "Source": "Referral", "Contact Person": "Ann", "Next Steps": "prep R2",
     "Highlight": "strong fit", "Feedback": "R1 ok", "Job URL": None,
     "Follow-up Reminder": "2099-01-01", "Date Applied": "2026-08-01"},
    {"notion_page_id": "bbb222", "Company": "Beta", "Status": "Applied",
     "Priority": "Low", "Next Steps": "wait", "Follow-up Reminder": None},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "09-projections").mkdir(parents=True)
    (ws / "03-materials").mkdir(parents=True)
    (ws / "12-intake").mkdir(parents=True)
    (ws / "10-briefs").mkdir(parents=True)
    (ws / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": ROWS}), encoding="utf-8")
    (ws / "03-materials" / "playbook.yaml").write_text(yaml.safe_dump([
        {"id": "P1", "pattern": "tenure", "status": "needs_work", "category": "叙事",
         "best_answer": "standard 30s", "engagements": []}], allow_unicode=True))
    (ws / "03-materials" / "capability.json").write_text(json.dumps({
        "built_at": "2026-08-08 10:00",
        "sources": {"jd_chars": 100, "evidence_n": 3, "gap_signals_n": 2},
        "dimensions": [{"name": "LLM 系统", "market": 5, "self": 4,
                        "evidence": ["RAG 架构答得顺"], "gap": "", "prep": []},
                       {"name": "K8s 运维", "market": 4, "self": 2,
                        "evidence": ["（暂无复盘证据）"], "gap": "多个 JD 要求集群管理",
                        "prep": ["搭一个 3 节点集群跑推理服务"]}],
        "strengths": ["LLM 系统——复盘证据扎实"], "focus": ["K8s——先搭集群"],
        "summary": "强在 LLM；缺 K8s；先动手搭。"}, ensure_ascii=False))
    (ws / "03-materials" / "resume.html").write_text(
        "<!DOCTYPE html><html><head></head><body>母版</body></html>")
    (ws / "03-materials" / "profile.json").write_text(json.dumps({
        "name": "Acme Candidate",
        "contact": [{"text": "acme@cand.com", "href": "mailto:acme@cand.com"}]}))
    (ws / "10-briefs" / "2026-08-07-Acme-brief.md").write_text("# Acme brief")
    from datetime import datetime, timedelta, timezone
    _sgt = timezone(timedelta(hours=8))
    _now = datetime.now(_sgt)
    _today = _now.strftime("%Y-%m-%d")
    (ws / "08-events").mkdir()
    (ws / "08-events" / "daemon-state.json").write_text(json.dumps({
        "last.gmail_scan": _now.isoformat(timespec="seconds"),
        "calendar_cache": {"at": _now.isoformat(timespec="seconds"),
                           "events": [{"start": f"{_today}T14:00:00+08:00",
                                       "end": f"{_today}T15:00:00+08:00",
                                       "title": "Acme AI 二面", "kind": "interview"},
                                      {"start": f"{_today}T10:00:00+08:00",
                                       "end": f"{_today}T11:00:00+08:00",
                                       "title": "Chat with Ann @ Acme AI", "kind": "block"},
                                      {"start": f"{_today}T19:00:00+08:00",
                                       "end": f"{_today}T20:00:00+08:00",
                                       "title": "朋友聚餐", "kind": "block"}]}}))
    (ws / "13-daily").mkdir()
    (ws / "13-daily" / "2026-08-03-weekly.md").write_text("# 周报\n漏斗 ok")
    (ws / "03-materials" / "achievement-bank.md").write_text(
        "# 战绩素材库\n\n> 唯一事实来源。\n\n"
        "## Alpha Corp — engineer 战绩\n- built engineer ml pipeline\n"
        "## 学术资产\n- papers\n"
        "## ⚠️ 素材使用注意\n1. 内部代号要转译。\n")
    (ws / "12-intake" / "p1.json").write_text(json.dumps({
        "kind": "lead.intake", "lead": {"company": "NewCo", "highlight": "x",
                                        "position": "AI Eng", "comp_mentions": [],
                                        "jd_excerpt": "need ml engineer, 5 yoe"},
        "dedupe": {"verdict": "new"}, "source_hint": "paste",
        "fit": {"fit": 4, "why": "对口", "flags": [],
                "req_gaps": [{"req": "fluent Thai", "verdict": "不符",
                              "note": "履历语言为中英"}]},
        "approved": None}))
    (ws / "11-shadow").mkdir()
    (ws / "11-shadow" / "s1.json").write_text(json.dumps({
        "company": "Acme AI", "notion_page_id": "aaa111",
        "field_diffs": {"Next Steps": "send thanks note"},
        "body_entry": "### 2026-08-07 R1 面试/Ann\n\n【录入】band 未披露",
        "playbook_updates": [], "sentinel": "PASS", "judgment": [],
        "approved": None}, ensure_ascii=False))
    (ws / "11-shadow" / "d1.json").write_text(json.dumps({
        "kind": "diary.entry", "notion_page_id": "dp",
        "body_entry": "### 2026-08-07\n今天推进两家", "approved": None},
        ensure_ascii=False))
    (ws / "12-intake" / "c1.json").write_text(json.dumps({
        "kind": "calendar.event", "company": "Acme AI", "notion_page_id": "aaa111",
        "title": "面试：Acme AI", "date": "", "time": "", "duration_min": 60,
        "note": "tracker 已排面但日历没这场", "approved": None}, ensure_ascii=False))

    cfg = Config(raw={
        "workspace_dir": str(ws),
        "notion": {"token": "fake", "tracker_data_source_id": "ds", "diary_page_id": "dp"},
        "sentinel": {"rules": [{"id": "codename", "type": "pattern", "action": "block",
                                "patterns": ["ProjectX"], "why": "internal"}]},
    }, path=tmp_path / "c.yaml")

    monkeypatch.setattr("joblander.web.app.load_config", lambda: cfg)
    monkeypatch.setattr(notion_mod.NotionClient, "_request",
                        lambda self, *a, **k: {"results": [], "id": "created"})
    monkeypatch.setenv("JOBLANDER_TASKS_SYNC", "1")   # 后台任务内联执行（同一链路）
    from joblander.web.app import TASKS, create_app
    TASKS.clear()
    # base_url 走 127.0.0.1：与真实运行同一条路径（同源守卫校验 Host/Origin），
    # TestClient 默认的 "testserver" 会被守卫按 DNS rebinding 拒掉。
    return TestClient(create_app(with_daemon=False), base_url="http://127.0.0.1")


def test_pages_render(client):
    for path, anchor in [("/", "指挥中心"), ("/pipeline", "Acme AI"),
                         ("/system", "口径守卫"),
                         ("/playbook", "tenure"),
                         ("/company/aaa111", "strong fit"),
                         ("/briefs/2026-08-07-Acme-brief.md", "Acme brief")]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert anchor in r.text, f"{path} 缺 {anchor}"


def test_company_stage_flow(client, tmp_path):
    """公司页阶段流转图：当前段 cur 高亮、已过段 done、多状态段显子状态；关闭态点亮岔道。"""
    co = client.get("/company/aaa111").text            # Interview Scheduled → 面试段
    assert 'class="fn cur"' in co and "多轮往复" in co
    assert co.count('class="fn done"') == 4            # 线索/评估中/待申请/申请初筛已过
    assert '<span class="fn exit"' in co               # 岔道在场但未点亮
    beta = client.get("/company/bbb222").text          # Applied → 申请/初筛段（多状态）
    assert '<b class="fsub">Applied</b>' in beta
    rows = [dict(r, Status="Rejected") if r["Company"] == "Beta" else r for r in ROWS]
    (tmp_path / "ws" / "09-projections" / "tracker.json").write_text(
        json.dumps({"rows": rows}), encoding="utf-8")
    closed = client.get("/company/bbb222").text        # 关闭态：主线全灭，岔道红亮
    assert '<span class="fn exit cur"' in closed and "Rejected" in closed
    assert 'class="fn cur"' not in closed.replace('"fn exit cur"', "")
    assert 'class="fn done"' not in closed


def test_drill_page_and_run(client):
    """练兵场：随机出题 302 定格到具体题；判题接口跑通正确/错误两路。"""
    r = client.get("/drill", follow_redirects=False)
    assert r.status_code == 302 and "/drill?id=" in r.headers["location"]
    html = client.get("/drill?id=jump-game").text
    assert "Jump Game" in html and "dr-code" in html and "换一题" in html
    assert ">参谋部</a>" in html and ">练兵场</a>" in html   # 侧栏：旧页改名 + 新页并存
    ok = client.post("/api/drill/run", data={
        "id": "jump-game",
        "code": ("class Solution:\n    def canJump(self, nums):\n"
                 "        reach = 0\n"
                 "        for i, x in enumerate(nums):\n"
                 "            if i > reach: return False\n"
                 "            reach = max(reach, i + x)\n"
                 "        return True\n")}).json()
    assert ok["verdict"] == "pass" and ok["passed"] == ok["total"]
    bad = client.post("/api/drill/run", data={"id": "nope", "code": "x"})
    assert bad.status_code == 400


def test_tools_dissolved_into_workflows(client):
    """UI v2：工具页解散——动作嵌入所在工作流，全局动作在侧栏（每页可达）。"""
    assert client.get("/tools").status_code == 404
    html = client.get("/pipeline").text
    assert "新机会" in html                             # 页内入口（dlg-intake）
    assert "看板" in html and "kcol" in html            # Kanban 视图
    for f in ("High", "Medium"):                        # 优先级筛选 chips
        assert f'data-f="{f}"' in html
    co = client.get("/company/aaa111").text
    for anchor in ("时间线", "评估匹配", "生成 brief", "转写 → 录入", "＋ 记录"):
        assert anchor in co, f"公司页缺 {anchor}"


def test_approvals_live_where_they_belong(client):
    """UI v2.1/v2.2：审批回属地——入池在新机会页、面后在公司页、日记在今天页。"""
    for path in ("/inbox", "/briefs"):
        assert client.get(path, follow_redirects=False).status_code == 302
    src = client.get("/sourcing").text
    assert "待入池" in src and "NewCo" in src and "否决所选" in src
    assert "scanbar" in src and "↻ 扫邮箱" in src and "↻ 扫 MCF" in src
    assert "上次扫" in src and "入库" in src              # 工具条时间 + 每条线索入库时间
    assert "⛔ fluent Thai" in src                         # requirements 初筛高亮
    assert "NewCo" not in client.get("/pipeline").text    # 机会页只管已有申请
    co = client.get("/company/aaa111").text
    assert "待你批" in co and "send thanks note" in co and "批准执行" in co
    dash = client.get("/").text
    assert "面后录入等你批" in dash and "日记草稿" in dash
    assert "已按匹配度排好" not in dash          # 线索决策只走侧栏新机会角标，不占首页待办


def test_scribe_approve_from_company_page(client, tmp_path):
    """公司页改后批 → 字段写回 + 投影同步 + 条目落地时间线。"""
    pf = str(tmp_path / "ws" / "11-shadow" / "s1.json")
    r = client.post("/api/proposal/amend_apply",
                    data={"file": pf, "Next Steps": "send thanks + ask band"})
    assert r.status_code == 200
    proj = json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert proj["rows"][0]["Next Steps"] == "send thanks + ask band"
    tl = (tmp_path / "ws" / "18-companies" / "Acme-AI" / "timeline.jsonl").read_text()
    assert "R1 面试/Ann" in tl and '"scribe"' in tl
    after = client.get("/company/aaa111").text
    assert "send thanks + ask band" not in after or "批准执行" not in after  # 待批卡消失
    assert "R1 面试/Ann" in after                               # 条目已现身时间线


def test_company_note_review_and_timeline(client, tmp_path):
    r = client.post("/api/company/note", data={
        "page_id": "aaa111", "kind": "call", "title": "HM 电话",
        "participants": "Ann, Bob", "content": "聊 team 与 band"})
    assert r.status_code == 200
    eid = r.json()["id"]
    tl = (tmp_path / "ws" / "18-companies" / "Acme-AI" / "timeline.jsonl").read_text()
    assert "HM 电话" in tl and '"human"' in tl
    r2 = client.post("/api/company/review", data={
        "page_id": "aaa111", "entry_id": eid, "text": "该问 band 没问"})
    assert r2.status_code == 200
    page = client.get("/company/aaa111").text
    assert "HM 电话" in page and "该问 band 没问" in page


def test_company_upload_and_file_guard(client, tmp_path):
    r = client.post("/api/company/upload",
                    data={"page_id": "aaa111", "kind": "jd", "entry_id": ""},
                    files={"file": ("jd v1.txt", b"need ml engineer", "text/plain")})
    assert r.status_code == 200
    rel = r.json()["file"]
    assert client.get(f"/files/{rel}").status_code == 200
    (tmp_path / "secret.md").write_text("outside")        # workspace 外的文件
    assert client.get("/files/..%2Fsecret.md").status_code == 404


def test_audio_attachment_served_playable(client):
    """面试录音（m4a 等）：能上传、能以音频 MIME 回放——octet-stream 会变成下载。"""
    r = client.post("/api/company/upload",
                    data={"page_id": "aaa111", "kind": "attachment", "entry_id": ""},
                    files={"file": ("面试录音.m4a", b"\x00fakeaudio", "audio/mp4")})
    assert r.status_code == 200
    got = client.get(f"/files/{r.json()['file']}")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("audio/mp4")


def test_dashboard_counts(client):
    html = client.get("/").text
    assert "待批提案" in html and "4" in html        # lead + scribe + diary + calendar
    assert "Acme AI" in html                          # High 战线
    assert "作战室排了面试" in html and "确认建事件" in html   # 排期缺口并入待办，来源写明


def test_capability_scope_config(client, tmp_path):
    """参谋部：JD 策略页面可配——默认 High；自定义点名落 capability.json；雷达延迟到 DOM 就绪再画。"""
    html = client.get("/playbook").text
    assert "JD 策略" in html and "High 优先级机会" in html
    assert 'value="Acme AI"' in html                                  # pool 公司可点名
    assert "addEventListener('DOMContentLoaded'" in html              # 雷达时序回归：app.js 是 defer 的
    r = client.post("/api/capability/scope",
                    data={"mode": "custom", "companies": "Acme AI"})
    assert r.json()["ok"] is True
    cap = json.loads((tmp_path / "ws" / "03-materials" / "capability.json").read_text())
    assert cap["jd_scope"] == {"mode": "custom", "companies": ["Acme AI"]}
    assert "自定义 1 家" in client.get("/playbook").text
    assert client.post("/api/capability/scope",
                       data={"mode": "custom", "companies": ""}).status_code == 400


def test_md_to_html_tables():
    """markdown 表格渲染成真 <table>（学术资产段曾被降级成等宽文本行）。"""
    from joblander.web.app import md_to_html
    h = md_to_html("| 项目 | 详情 |\n|---|---|\n| Ph.D. | **NLP** SUTD |\n\n- 列表照旧")
    assert "<table>" in h and "<th>项目</th>" in h and "<td>Ph.D.</td>" in h
    assert "<b>NLP</b> SUTD" in h and "---" not in h
    assert "<li>列表照旧</li>" in h
    assert md_to_html("| a |").count("<table>") == 1     # 无分隔行也成表


def test_arsenal_page_edit_add(client, tmp_path):
    """弹药库：按段展示可编辑；内部「使用注意」段不上屏但文件里保留；新增段插在规则前。"""
    html = client.get("/arsenal").text
    assert "Alpha Corp — engineer 战绩" in html and "ml pipeline" in html
    assert "内部代号要转译" not in html                       # 内部段不展示
    assert "1 段内部使用规则" in html
    r = client.post("/api/arsenal/save", data={
        "idx": 0, "title": "Alpha Corp — Staff MLE",
        "body": "- **R**：FCR +12pp", "orig_title": "Alpha Corp — engineer 战绩"})
    assert r.json()["ok"] is True
    bank = (tmp_path / "ws" / "03-materials" / "achievement-bank.md").read_text()
    assert "Staff MLE" in bank and "+12pp" in bank
    assert "素材使用注意" in bank and "唯一事实来源" in bank    # 内部段与文件头保留
    stale = client.post("/api/arsenal/save", data={
        "idx": 0, "title": "x", "body": "y", "orig_title": "Alpha Corp — engineer 战绩"})
    assert stale.status_code == 400                            # 标题已变，旧句柄拒写
    r = client.post("/api/arsenal/add", data={
        "title": "joblander —— 个人项目", "body": "- **R**：149 tests"})
    assert r.json()["ok"] is True
    bank = (tmp_path / "ws" / "03-materials" / "achievement-bank.md").read_text()
    assert bank.index("joblander") < bank.index("素材使用注意")  # 素材归素材，规则垫底
    dup = client.post("/api/arsenal/add", data={"title": "joblander —— 个人项目", "body": "z"})
    assert dup.status_code == 400
    assert 'href="/arsenal"' in client.get("/playbook").text    # 参谋部入口改指弹药库


def test_command_center_v3(client, tmp_path):
    """指挥中心 v3：问候语提供情绪价值；近 4 天场次；日记定稿入日报；手记人工段。"""
    from joblander.web.app import GREETINGS
    html = client.get("/").text
    assert any(g in html for slot in GREETINGS.values() for g in slot)   # h1 = 问候语
    assert "近 4 天场次" in html and "今天" in html
    assert "Acme AI 二面" in html                                       # kind=interview 进
    assert "Chat with Ann @ Acme AI" in html                            # 公司名兜底进（无关键词标题）
    assert "朋友聚餐" not in html                                       # 私人日程不上指挥中心
    assert "弹药就绪" not in html and "系统事件" not in html             # 面向系统的段清场
    assert "今日日记" in html and "我的手记" in html
    # 日记草稿：编辑后定稿 → 落 13-daily 的「今日日记」段（amend + apply 一步）
    r = client.post("/api/proposal/amend_apply", data={
        "file": str(tmp_path / "ws" / "11-shadow" / "d1.json"),
        "body_entry": "### 今天\n【进展】Acme R2 打完，手感不错"})
    assert r.status_code == 200
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    daily = (tmp_path / "ws" / "13-daily" / f"{today}.md").read_text()
    assert "手感不错" in daily and "## 今日日记" in daily
    # 手记：人工段直接保存，与 AI 段分开
    r = client.post("/api/daily/notes", data={"name": f"{today}.md",
                                              "text": "今天节奏稳，明天冲 Chanel。"})
    assert r.json()["ok"] is True
    daily = (tmp_path / "ws" / "13-daily" / f"{today}.md").read_text()
    assert "## 我的手记" in daily and "节奏稳" in daily and "手感不错" in daily
    assert "冲 Chanel" in client.get("/").text                          # 回显在指挥中心
    assert client.post("/api/daily/notes",
                       data={"name": "../x.md", "text": "y"}).status_code == 400


def test_refresh_all_sources(client, tmp_path, monkeypatch):
    """全量刷新：数据源行可见；手动端点各自打新鲜度时间戳；日历刷新写缓存。"""
    html = client.get("/").text
    assert "数据源：" in html and "全量刷新" in html and "refreshAll" in html
    r = client.post("/api/pull")
    assert r.status_code == 200
    state = json.loads((tmp_path / "ws" / "08-events" / "daemon-state.json").read_text())
    assert state.get("last.notion_pull")                       # 手动 pull 打了戳
    assert client.post("/api/calendar/refresh").status_code == 400   # 未接入日历 → 明说
    (tmp_path / "ws" / ".credentials").mkdir()
    (tmp_path / "ws" / ".credentials" / "calendar_token.json").write_text("{}")
    monkeypatch.setattr("joblander.calendar_sync.upcoming_events",
                        lambda cfg, days=7: [{"start": "2026-08-09T14:00:00+08:00",
                                              "end": "2026-08-09T15:00:00+08:00",
                                              "title": "Beta 一面", "kind": "interview"}])
    r = client.post("/api/calendar/refresh")
    assert r.json()["events"] == 1
    state = json.loads((tmp_path / "ws" / "08-events" / "daemon-state.json").read_text())
    assert state["calendar_cache"]["events"][0]["title"] == "Beta 一面"
    assert state.get("last.calendar_watch")


def test_company_entry_edit_api(client, tmp_path):
    """公司页事件可编辑：编辑表单在页面上；API 改字段落 timeline。"""
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")
    e = cf.timeline_add(cfg, "Acme AI", kind="note", title="记录", date="2026-08-06",
                        content_md="原文")
    co = client.get("/company/aaa111").text
    assert "✎ 编辑" in co and "saveEntry" in co
    assert 'class="eview"' in co                       # view/edit 同区切换：查看态有包壳
    r = client.post("/api/company/entry/edit", data={
        "page_id": "aaa111", "entry_id": e["id"], "date": "2026-08-06", "title": "记录",
        "kind": "call", "new_title": "Ann 初聊", "participants": "Ann、Bob",
        "review": "该问 band 没问", "review_set": "1"})
    assert r.json()["ok"] is True
    got = cf.local_entries(cfg, "Acme AI")[-1]
    assert got["kind"] == "call" and got["title"] == "Ann 初聊"
    assert got["participants"] == ["Ann", "Bob"] and got["content_md"] == "原文"
    assert got["my_review"]["text"] == "该问 band 没问"   # 复盘随统一保存落档
    r = client.post("/api/company/entry/edit", data={
        "page_id": "aaa111", "entry_id": e["id"], "date": "2026-08-06",
        "title": "Ann 初聊", "kind": "call", "review": "",
        "review_set": "1"})                               # 清空即删
    assert r.json()["ok"] is True
    assert not cf.local_entries(cfg, "Acme AI")[-1].get("my_review")
    # GitHub 风编辑器：tab 预览 + 附件管理
    co = client.get("/company/aaa111").text
    assert "mdtabs" in co and "attmgr" in co
    prev = client.post("/api/md/preview", data={"text": "### 小节\n- 一条"}).json()
    assert "<h4>小节</h4>" in prev["html"] and "<li>一条</li>" in prev["html"]
    # 附件：绑 → 解绑（文件保留，且不被自动绑回）
    saved = cf.save_upload(cfg, "Acme AI", "纪要-2026-08-06.pdf", b"x", "attachment")
    rel = str(saved.relative_to(cfg.workspace_dir))
    cf.update_entry(cfg, "Acme AI", e["id"], {"attachments": [rel]})
    r = client.post("/api/company/entry/detach", data={
        "page_id": "aaa111", "entry_id": e["id"], "rel": rel})
    assert r.json()["ok"] is True
    got = cf.local_entries(cfg, "Acme AI")[-1]
    assert got["attachments"] == [] and rel in got["detached_atts"]
    assert saved.exists()                                   # 文件不销毁
    orphans = cf.bind_orphan_attachments(cfg, "Acme AI")
    assert any(o["rel"] == rel for o in orphans)            # 名字带日期也不许自动绑回
    assert cf.local_entries(cfg, "Acme AI")[-1]["attachments"] == []


def test_resume_customiser_flow(client, tmp_path, monkeypatch):
    """定制简历唯一入口：空消息出首版（单轮，无自动评审）；纯提问只回话不烧版本；
    带意见消息教练接住 + 累积进 feedback；出版永远带上全部累积意见；评审改按钮手动触发。"""
    import json as _json
    content = {"tagline": "AI Engineer", "summary": ["对准 Acme JD 的定制版 Summary。"],
               "experience": [{"company": "ExCo", "position": "Engineer",
                               "when": "Singapore · 2020-2024", "note": "",
                               "bullets": ["<strong>战绩</strong>对准 Acme 的 agent 平台定位"]}],
               "skills": [{"label": "LLM", "value": "RAG, agents"}],
               "education": [], "publications": [], "service": "",
               "changes": ["Summary 对准 Acme 的 agent 平台定位"]}
    recruiter = _json.dumps({"screen": {"pass": "yes", "flags": []},
                             "hm": {"read": "yes", "jd_fit": [], "probes": [],
                                    "weak_bullets": []},
                             "verdict": {"interview": "yes", "one_line": "solid",
                                         "top_fixes": []}}, ensure_ascii=False)
    coach = _json.dumps({"agent_fixable": [], "needs_user": []})

    class Seq:
        def __init__(self): self.resp, self.calls = [], []
        def generate(self, prompt, system=None, json_mode=False):
            self.calls.append(prompt)
            return self.resp.pop(0)
    seq = Seq()
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": seq)
    monkeypatch.setattr("joblander.resume_agent._to_pdf", lambda p: None)

    seq.resp = [_json.dumps(content, ensure_ascii=False)]  # 单轮产版：一次 LLM 调用，无自动评审
    r = client.post("/api/resume/react", data={"page_id": "aaa111", "message": ""})
    assert r.json()["ok"] is True and r.json()["task"]     # 后台任务：托盘接管
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "定制" in t["label"] for t in tasks)
    tid = next(t["id"] for t in tasks if "定制" in t["label"])
    client.post("/api/tasks/dismiss", data={"id": tid})
    assert all(t["id"] != tid for t in client.get("/api/tasks").json())
    co = client.get("/company/aaa111").text
    assert "ResumeCustomiserAgent" in co and "v1" in co
    assert "出下一版" in co and "版本只增不覆盖" in co  # 唯一动作 + 版本语义
    assert "metaKey" in co and "ctrlKey" in co              # ⌘/Ctrl+Enter 发送，Enter 只换生
    assert "v1 出炉" in co and "Summary 对准 Acme 的 agent 平台定位" in co   # 版本=对话事件
    assert "评审这版" in co                                  # 未评审版本给出手动评审按钮

    seq.resp = [_json.dumps({"reply": "问得好：取舍按 JD 排",   # 纯提问 → 只回话
                             "facts": [], "opinions": []}, ensure_ascii=False)]
    r2 = client.post("/api/resume/react",
                     data={"page_id": "aaa111", "message": "为什么这样排？"})
    assert r2.json()["chat"]["reply"].startswith("问得好")
    assert "task" not in r2.json()                          # 不烧版本

    seq.resp = [_json.dumps({"reply": "记下了——说「出一版」或点 ⚙ 即出新版",
                             "generate": False, "facts": [],
                             "opinions": ["agent 一节放最前"]}, ensure_ascii=False)]
    r3 = client.post("/api/resume/react",                   # 提意见 ≠ 出版：聊归聊
                     data={"page_id": "aaa111", "message": "把 agent 一节放最前"})
    assert "task" not in r3.json() and r3.json()["chat"]["opinions"]
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")
    st = cf.load_meta(cfg, "Acme AI").get("resume") or {}
    assert st.get("feedback") == ["agent 一节放最前"]        # 意见并入累积集合

    content_v2 = dict(content, changes=["合并了 agent 平台条目并前置"])
    seq.resp = [_json.dumps({"reply": "这就出", "generate": True, "facts": [],
                             "opinions": []}, ensure_ascii=False),
                _json.dumps(content_v2, ensure_ascii=False)]   # 显式「出一版」→ 单轮生成
    r4 = client.post("/api/resume/react", data={"page_id": "aaa111", "message": "出一版吧"})
    assert r4.json()["task"] and r4.json()["chat"]["generate"] is True
    assert any("agent 一节放最前" in c and "上一版" not in c
               for c in seq.calls)                          # v2 带累积意见，不再基于上一版 HTML
    st = cf.load_meta(cfg, "Acme AI").get("resume") or {}
    assert len(st.get("versions") or []) == 2
    assert st.get("feedback") == ["agent 一节放最前"]        # 持久保留，不因出版清空
    ars = client.get("/arsenal").text
    assert "简历母版" in ars and "Acme AI" not in ars       # 定制版不在弹药库陈列（在公司页对话里）

    # 手动评审当前版：招聘方盲评 + 教练分拣，回写版本条目
    seq.resp = [recruiter, coach]
    r5 = client.post("/api/resume/eval", data={"page_id": "aaa111", "version": "resume-v2"})
    assert r5.json()["ok"] is True and r5.json()["task"]
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "评估" in t["label"] for t in tasks)
    co_ev = client.get("/company/aaa111").text
    assert "邀约" in co_ev and "solid" in co_ev              # 评审结果落进版本卡片

    # 清空重来：版本+对话归档（不物理删除），meta 归零；投出的版本记录保留
    client.post("/api/company/meta", data={"page_id": "aaa111", "resume_variant": "v2"})
    co2 = client.get("/company/aaa111").text
    assert "清空重来" in co2
    r6 = client.post("/api/resume/reset", data={"page_id": "aaa111"})
    assert r6.json()["ok"] is True and r6.json()["archived"] >= 2   # v1/v2 html+chat.json
    st2 = cf.load_meta(cfg, "Acme AI").get("resume") or {}
    assert not st2.get("versions") and not st2.get("feedback") and not st2.get("asked_user")
    rdir = tmp_path / "ws" / "18-companies" / "Acme-AI" / "resume"
    arch = [d for d in rdir.iterdir() if d.is_dir() and d.name.startswith("archive-")]
    assert arch and any(f.name == "resume-v1.html" for f in arch[0].iterdir())
    assert not [f for f in rdir.iterdir() if f.is_file()]           # 现场清空
    co3 = client.get("/company/aaa111").text
    assert "还没有版本" in co3                                      # 教练回到开场白
    assert "v2（旧记录）" in co3                                    # 投递事实不丢


def test_priority_editable_and_row_archive(client, tmp_path):
    """公司页：优先级可点改；删除=Notion 归档+投影移除，本地档案保留。"""
    co = client.get("/company/aaa111").text
    assert 'data-field="Priority"' in co and 'data-opts=",High,Medium,Low"' in co
    assert "delRow" in co and "🗑 删除" in co
    r = client.post("/api/row/update", data={
        "page_id": "aaa111", "field": "Priority", "value": "Medium"})
    assert r.json()["ok"] is True
    proj = json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert proj["rows"][0]["Priority"] == "Medium"
    # 删除 Beta 行
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")
    cf.timeline_add(cfg, "Beta", kind="note", title="留档", content_md="历史")
    r = client.post("/api/row/archive", data={"page_id": "bbb222"})
    assert r.json()["ok"] is True and r.json()["company"] == "Beta"
    proj = json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert all(x.get("Company") != "Beta" for x in proj["rows"])
    assert cf.local_entries(cfg, "Beta")                     # 本地档案不动
    assert "row.archived" in (tmp_path / "ws" / "08-events" / "event-log.jsonl").read_text()
    assert client.post("/api/row/archive", data={"page_id": "nope"}).status_code == 400


def test_quick_actions_removed(client):
    html = client.get("/").text
    assert "随手" not in html and "口径检查" not in html
    assert client.post("/api/check", data={"text": "x"}).status_code == 404
    assert 'id="dlg-intake"' in html                  # 弹窗保留（作战室/新机会页按钮复用）


def test_row_update_writes_projection_and_event(client, tmp_path):
    r = client.post("/api/row/update", data={
        "page_id": "aaa111", "field": "Next Steps", "value": "ship it"})
    assert r.json()["ok"] is True
    proj = json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert proj["rows"][0]["Next Steps"] == "ship it"
    events = (tmp_path / "ws" / "08-events" / "event-log.jsonl").read_text()
    assert "row.edited" in events


def test_row_update_rejects_bad_field(client):
    r = client.post("/api/row/update", data={"page_id": "aaa111", "field": "Feedback",
                                             "value": "x"})
    assert r.status_code == 400


def test_company_name_editable_and_local_dir_follows(client, tmp_path):
    """公司页标题可点改公司名；本地档案（时间线/附件目录）跟着改名走，
    不然改完名字看起来像丢了历史。"""
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")
    cf.timeline_add(cfg, "Acme AI", kind="note", title="备注", content_md="历史记录")

    co = client.get("/company/aaa111").text
    assert 'data-field="Company"' in co and 'data-cur="Acme AI"' in co
    r = client.post("/api/row/update", data={
        "page_id": "aaa111", "field": "Company", "value": "Acme AI Pte Ltd"})
    assert r.json()["ok"] is True
    proj = json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert proj["rows"][0]["Company"] == "Acme AI Pte Ltd"
    assert not (tmp_path / "ws" / "18-companies" / "Acme-AI").exists()
    assert (tmp_path / "ws" / "18-companies" / "Acme-AI-Pte-Ltd").exists()
    assert cf.local_entries(cfg, "Acme AI Pte Ltd")[0]["title"] == "备注"   # 时间线跟着搬了
    co2 = client.get("/company/aaa111").text
    assert "Acme AI Pte Ltd" in co2 and "备注" in co2


def test_intake_approve_flow(client, tmp_path):
    pf = str(tmp_path / "ws" / "12-intake" / "p1.json")
    r = client.post("/api/proposal/apply", data={"file": pf})
    assert r.status_code == 200
    data = json.loads((tmp_path / "ws" / "12-intake" / "p1.json").read_text())
    assert data["approved"] is True
    assert "NewCo" not in client.get("/sourcing").text       # 待入池清空
    tl = (tmp_path / "ws" / "18-companies" / "NewCo" / "timeline.jsonl").read_text()
    assert '"intake"' in tl                                  # 入池即建档
    jd = list((tmp_path / "ws" / "18-companies" / "NewCo" / "jd").glob("*.txt"))
    assert jd and "need ml engineer" in jd[0].read_text()    # JD 随入池落档


def test_reject_flow(client, tmp_path):
    pf = tmp_path / "ws" / "12-intake" / "p2.json"
    pf.write_text(json.dumps({"kind": "lead.intake", "lead": {"company": "Z"},
                              "dedupe": {"verdict": "new"}, "approved": None}))
    client.post("/api/proposal/reject", data={"file": str(pf), "reason": "noise"})
    assert json.loads(pf.read_text())["approved"] is False


def test_brief_generation(client, tmp_path, monkeypatch):
    import json as _json
    from joblander.llm import MockLLM
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": MockLLM([
        _json.dumps({"situation": "R1 已过，R2 定生死", "strategy": ["展开 pipeline 到架构层"],
                     "qa_prep": [], "asks": ["最痛的技术问题"],
                     "watchouts": []}, ensure_ascii=False)]))
    r = client.post("/api/brief", data={"company": "Acme", "note": "R2 focus"})
    assert r.status_code == 200 and r.json()["task"]          # 后台任务化
    briefs = sorted((tmp_path / "ws" / "10-briefs").glob("*Acme*.md"),
                    key=lambda p: p.stat().st_mtime)
    assert briefs, "同步任务模式下 brief 应已落盘"
    text = briefs[-1].read_text(encoding="utf-8")
    assert "接下来的打法" in text and "R2 定生死" in text      # LLM 参谋层落地
    assert "红线口径 → /system" in text and "R2 focus" in text  # 只指路不复印

    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws"), "notion": {"token": "x"}},
                 path=tmp_path / "c.yaml")
    tl = [e for e in cf.local_entries(cfg, "Acme AI")
          if (e.get("title") or "").startswith("参谋 Brief")]
    assert len(tl) == 1                                       # brief 上了时间线
    co = client.get("/company/aaa111").text
    assert f"/company/aaa111/entry/{tl[0]['id']}" in co       # ⛶ 全屏入口在
    full = client.get(f"/company/aaa111/entry/{tl[0]['id']}")
    assert full.status_code == 200 and "局面" in full.text    # 全屏阅读页
    assert "回 Acme AI 时间线" in full.text
    assert "我的复盘" in full.text and "doc-rev" in full.text   # 复盘全屏可读可改
    r = client.post("/api/company/review", data={
        "page_id": "aaa111", "entry_id": tl[0]["id"], "text": "brief 打法奏效"})
    assert r.status_code == 200
    assert "brief 打法奏效" in client.get(
        f"/company/aaa111/entry/{tl[0]['id']}").text          # 存了再开，预填在
    assert client.get("/company/aaa111/entry/nope").status_code == 404


def test_visibility_batch(client):
    """把「引擎在用但看不见」的数据亮出来：今日场次/复盘沉淀/系统健康/wsdoc。"""
    dash = client.get("/").text
    assert "近 4 天场次" in dash and "Acme AI 二面" in dash
    pb = client.get("/playbook").text
    assert "复盘存档" in pb and "2026-08-03-weekly.md" in pb and "弹药库" in pb
    assert "能力画像" in pb and "K8s 运维" in pb and "缺口 2" in pb   # 雷达数据 + 缺口标记
    assert "叙事（1）" in pb                                          # 模式按类型分组
    assert client.get("/wsdoc/13-daily/2026-08-03-weekly.md").status_code == 200
    assert client.get("/wsdoc/01-profile/secret.md").status_code == 404   # 白名单外拒
    sys_html = client.get("/system").text
    assert "外部连接" in sys_html and "常驻作业" in sys_html


def test_offers_page_and_save(client, tmp_path):
    assert client.get("/offers").status_code == 200
    r = client.post("/api/offers/save", json={"offers": [
        {"name": "TestCo", "base_monthly": 10000, "currency": "SGD",
         "bonus_months": 2, "equity_face_annual": 0, "equity_tier": "heavy",
         "bonus_guaranteed": True, "notes": "hypothetical"}]})
    assert r.status_code == 200 and r.json()["n"] == 1
    saved = json.loads((tmp_path / "ws" / "15-offers" / "offers.json").read_text())
    assert saved[0]["name"] == "TestCo" and saved[0]["bonus_guaranteed"] is True
    assert "TestCo" in client.get("/offers").text


def test_company_brief_button_attribute_intact(client):
    """回归：公司名经 tojson 进双引号属性会被裸引号截断（生成 brief 按钮连坏两轮的根因）。"""
    html = client.get("/company/aaa111").text
    assert 'data-co="Acme AI"' in html
    assert '{company:"' not in html          # 属性内不得再出现裸引号 JSON


def test_coordinator_slots_endpoint(client, monkeypatch):
    """W6 排期参谋端点：任务化执行，产物（时段对照+草稿）落公司档案时间线。"""
    import json as _json

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            if json_mode:
                return _json.dumps({"slots": [{"start": "2026-08-20T10:00",
                                               "end": "2026-08-20T11:00", "label": "Wed 10am"}],
                                    "duration_min": 60, "sender": "Jane", "notes": ""})
            return "Hi Jane, Wednesday 10am SGT works for me."
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    r = client.post("/api/coordinator/slots",
                    data={"page_id": "aaa111", "text": "Would Wed 10am SGT work for you?"})
    assert r.json()["ok"] is True and r.json()["task"]
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "排期参谋" in t["label"] for t in tasks)
    co = client.get("/company/aaa111").text
    assert "排期参谋" in co and "回复草稿" in co and "Wednesday 10am" in co
    # 太短的邀约直接 400，不烧模型
    r = client.post("/api/coordinator/slots", data={"page_id": "aaa111", "text": "hi"})
    assert r.status_code == 400


def test_scribe_proposal_apply_end_to_end(client, tmp_path):
    """Scribe 是正式提案流（历史名 shadow）：批准 → tracker 字段 + 档案时间线全落地。"""
    pf = tmp_path / "ws" / "11-shadow" / "s1.json"
    r = client.post("/api/proposal/apply", data={"file": str(pf)})
    out = r.json()
    assert r.status_code == 200 and out.get("dry_run") is False
    assert out.get("timeline")                          # 正文条目已入档案时间线
    co = client.get("/company/aaa111").text
    assert "send thanks note" in co                     # 字段 diff 落进投影行
    assert "band 未披露" in co                          # 时间线可见
    assert json.loads(pf.read_text(encoding="utf-8"))["approved"] is True  # 提案归档离队


def test_company_research_endpoint(client, tmp_path, monkeypatch):
    """W2 尽调端点（ADR-16 单路径）：贴入材料成为种子 → 尽调员判读后综合，
    档案落盘，页面折叠区可见。"""
    import json as _json

    class L:
        def generate(self, prompt, system=None, json_mode=False, effort=None):
            if "判缺口" in (system or ""):                    # ReAct 判读轮
                assert "内部消息" in prompt                    # 贴入材料进判读摘录
                return _json.dumps({"thought": "种子够用", "coverage": {}, "queries": []})
            assert "综合简介" in (system or "")                # synth 轮
            return _json.dumps({
                "summary_md": "**这家公司是谁** AI 平台团队 30 人 [1]", "card": [],
                "facts": [{"claim": "AI 平台团队 30 人", "category": "org",
                           "source": "[1] 贴入材料", "confidence": "medium"}],
                "salary_signals": [], "risks": [], "gaps": ["缺薪酬 band"]})
    import joblander.llm as llm_mod
    monkeypatch.setattr("joblander.sourcing.mcf_search",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    orig = llm_mod.from_config
    llm_mod.from_config = lambda cfg, tier="pro": L()
    try:
        r = client.post("/api/company/research",
                        data={"page_id": "aaa111", "notes": "内部消息：AI 平台团队 30 人"})
        assert r.json()["ok"] is True
        tasks = client.get("/api/tasks").json()
        assert any(t["status"] == "done" and "尽调" in t["label"] for t in tasks)
        d = _json.loads((tmp_path / "ws" / "14-dossiers" / "Acme-AI.json")
                        .read_text(encoding="utf-8"))
        assert d["seeded"]["materials"] == ["贴入材料"]        # 喂料入档可审计
        co = client.get("/company/aaa111").text
        assert "调研档案" in co and "AI 平台团队 30 人" in co
        assert "喂入 1 份" in co                               # 时间线摘要点明种子数
    finally:
        llm_mod.from_config = orig


def test_company_jd_paste_and_view(client, tmp_path, monkeypatch):
    """JD 贴入（2026-08-11 报障三连）：全文落档 + 系统内阅读；纯链接自动抓正文
    存成 md，Job URL 为空顺手补上；JD 链接格可原位编辑（链接移出 edc）。"""
    import json as _json
    r = client.post("/api/company/jd_paste",
                    data={"page_id": "aaa111", "text": "Senior AI Engineer\n负责 LLM 平台"})
    out = r.json()
    assert r.status_code == 200 and out["file"].endswith(".md")
    co = client.get("/company/aaa111").text
    assert f"/company/aaa111/jd/{out['file']}" in co        # pill 走系统内阅读路由
    assert 'title="点击原位编辑"' in co                      # JD 链接格可点（原来被 ↗ 吃掉）
    view = client.get(f"/company/aaa111/jd/{out['file']}").text
    assert "负责 LLM 平台" in view and "人工贴入" in view

    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Beta Engineer JD body. " * 30)
    r = client.post("/api/company/jd_paste",
                    data={"page_id": "bbb222", "text": "https://beta.example/jd/1"})
    out = r.json()
    assert r.status_code == 200 and out["url_filled"] is True
    rows = _json.loads((tmp_path / "ws" / "09-projections" / "tracker.json")
                       .read_text(encoding="utf-8"))["rows"]
    beta = next(x for x in rows if x["Company"] == "Beta")
    assert beta["Job URL"] == "https://beta.example/jd/1"   # 空链接顺手补上
    view = client.get(f"/company/bbb222/jd/{out['file']}").text
    assert "链接抓取" in view and "beta.example" in view


def test_jd_delete_and_link_repaste_refreshes(client, tmp_path, monkeypatch):
    """JD 生命周期：同链接重贴 = 刷新旧快照（进回收站不叠加）；✕ 删除走墓碑，
    页面即刻消失。"""
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Requirements: LLM platform. " * 30)
    f1 = client.post("/api/company/jd_paste",
                     data={"page_id": "aaa111",
                           "text": "https://acme.example/jd"}).json()["file"]
    f2 = client.post("/api/company/jd_paste",
                     data={"page_id": "aaa111",
                           "text": "https://acme.example/jd"}).json()["file"]
    jd = tmp_path / "ws" / "18-companies" / "Acme-AI" / "jd"
    active = [p.name for p in jd.iterdir() if p.is_file()]
    assert active == [f2]                            # 只剩新快照，旧的没叠加
    assert any((jd / ".trash").iterdir())            # 旧快照在回收站
    r = client.post("/api/company/jd_delete", data={"page_id": "aaa111", "name": f2})
    assert r.status_code == 200 and r.json()["ok"]
    assert [p.name for p in jd.iterdir() if p.is_file()] == []
    assert f2 not in client.get("/company/aaa111").text


def test_jd_edit_roundtrip(client, tmp_path):
    """JD 编辑（✎）：取原文 → 改写落档，旧版进 jd/.trash 可恢复；
    PDF 不可编辑（只能删了重传），空内容拒收。"""
    f = client.post("/api/company/jd_paste",
                    data={"page_id": "aaa111", "text": "旧版正文"}).json()["file"]
    r = client.get("/api/company/jd_raw", params={"page_id": "aaa111", "name": f})
    assert r.status_code == 200 and "旧版正文" in r.json()["text"]
    r = client.post("/api/company/jd_edit",
                    data={"page_id": "aaa111", "name": f, "text": "# 新版\n改后正文"})
    assert r.status_code == 200 and r.json()["edited"] == f
    jd = tmp_path / "ws" / "18-companies" / "Acme-AI" / "jd"
    assert "改后正文" in (jd / f).read_text(encoding="utf-8")
    baks = list((jd / ".trash").glob("*改前*"))
    assert baks and "旧版正文" in baks[0].read_text(encoding="utf-8")
    (jd / "role.pdf").write_bytes(b"%PDF-1.4 x")
    assert client.get("/api/company/jd_raw",
                      params={"page_id": "aaa111", "name": "role.pdf"}
                      ).status_code == 400
    assert client.post("/api/company/jd_edit",
                       data={"page_id": "aaa111", "name": "role.pdf",
                             "text": "x"}).status_code == 400
    assert client.post("/api/company/jd_edit",
                       data={"page_id": "aaa111", "name": f,
                             "text": "  "}).status_code == 400
    assert client.get("/api/company/jd_raw",
                      params={"page_id": "aaa111", "name": "../evil"}
                      ).status_code == 400


def test_jd_view_pdf_passthrough(client, tmp_path):
    """JD 阅读路由：文本渲染，PDF 一类转 /files 原样打开。"""
    d = tmp_path / "ws" / "18-companies" / "Acme-AI" / "jd"
    d.mkdir(parents=True, exist_ok=True)
    (d / "role.pdf").write_bytes(b"%PDF-1.4 x")
    r = client.get("/company/aaa111/jd/role.pdf", follow_redirects=False)
    assert r.status_code in (302, 307) and "/files/" in r.headers["location"]
    assert client.get("/company/aaa111/jd/../evil", follow_redirects=False).status_code == 404


def test_pipeline_marks_companies_awaiting_me(client):
    """作战室 ⚑ 标记：锚在公司的待批提案（scribe+calendar）让「哪家在等我」
    一目了然——卡片与表格行标「待你 N 件」，chips 一键筛出；无待办不标。"""
    html = client.get("/pipeline").text
    assert 'data-f="⚑"' in html                      # 筛选 chip
    assert "⚑ 待你 2 件" in html                     # Acme：scribe s1 + calendar c1
    assert html.count("⚑ 待你") == 1                 # Beta 无待办不标；日记不锚公司
    assert "⚑ 2" in html                             # 表格行同标


def test_manual_my_flag_marks_and_highlights(client):
    """手动「在你手上」旗标 vs 自动待办：两种「等你动手」信号视觉分开——
    自动待办（未批提案/到期 follow-up）琥珀 due，手动旗标红色 mine，不再混成一个意思。
    卡片角标切换、chips 同筛；档案页同一开关；取消即撤。"""
    html = client.get("/pipeline").text
    assert html.count('kcard hi due') + html.count('kcard  due') == 1     # 只有 Acme（自动待办）
    assert " mine" not in html                        # 没人手动标过，mine 还不该出现
    r = client.post("/api/company/flag", data={"page_id": "bbb222", "on": "1"})
    assert r.status_code == 200 and r.json()["flag"] is True
    html = client.get("/pipeline").text
    assert "⚑ 在你手上" in html                       # Beta 挂上手动旗
    assert html.count('kcard  mine') == 1              # Beta 卡片突出（红）
    assert 'class="mine"' in html                       # Beta 表格行也突出
    assert html.count('kcard hi due') + html.count('kcard  due') == 1   # Acme 仍是 due，没被带偏
    co = client.get("/company/bbb222").text
    assert "⚑ 在你手上" in co                         # 档案页开关反映状态
    r = client.post("/api/company/flag", data={"page_id": "bbb222", "on": "0"})
    assert r.json()["flag"] is False
    html = client.get("/pipeline").text
    assert "⚑ 在你手上" not in html                   # 取消即撤
    assert "⚐" in html                                # 未标卡片留角标入口


def test_intake_with_jd_attachment(client, tmp_path, monkeypatch):
    """新机会录入带 JD 附件（2026-08-11 报障）：正文进抽取语料，
    提案记 jd_file，批准后附件落公司 jd/、暂存清走。"""
    import json as _json
    seen = {}

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            seen.setdefault("prompt", prompt)          # 只记第一趟（scout 抽取）
            return _json.dumps({"company": "Newco", "position": "AI Engineer",
                                "category": "job_lead", "highlight": "x",
                                "suggested_next_step": "投", "urls": [],
                                "comp_mentions": ["总包面议"]})
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    r = client.post("/api/intake", data={"text": "", "source": "paste"},
                    files={"file": ("Newco_JD.txt",
                                    b"Newco is hiring an AI Engineer. " * 10, "text/plain")})
    out = r.json()
    assert r.status_code == 200, out
    assert "JD 附件原文" in seen["prompt"] and "Newco is hiring" in seen["prompt"]
    pf = tmp_path / "ws" / "12-intake" / out["proposal"]
    prop = _json.loads(pf.read_text(encoding="utf-8"))
    assert prop["jd_file"].startswith("12-intake/files/")
    pending = tmp_path / "ws" / prop["jd_file"]
    assert pending.exists()

    r = client.post("/api/proposal/apply", data={"file": str(pf)})
    assert r.status_code == 200
    names = [p.name for p in
             (tmp_path / "ws" / "18-companies" / "Newco" / "jd").iterdir()]
    assert "Newco_JD.txt" in names                     # 附件随批准落公司档案
    assert not pending.exists()                        # 暂存清走


def test_lead_approve_triggers_referral_hook(client, tmp_path, monkeypatch):
    """W14：入池批准 → 自动跑内推匹配落时间线（含触达草稿围栏，他来发）。"""
    import json as _json
    (tmp_path / "ws" / "04-pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ws" / "04-pipeline" / "referral-map.md").write_text(
        "## RefCo\n- Alice Chen（前同事，RefCo 平台组 EM，微信可达）", encoding="utf-8")

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            assert "Alice Chen" in prompt          # 地图真实进了语料
            return _json.dumps({"matches": [{"name": "Alice Chen", "why": "平台组 EM，直属相关",
                                             "channel": "wechat"}],
                                "second_degree": [], "blind_spot": "",
                                "outreach_draft": "Hi Alice，看到 RefCo 在招…"})
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    pf = tmp_path / "ws" / "12-intake" / "ref1.json"
    pf.write_text(_json.dumps({"kind": "lead.intake",
                               "lead": {"company": "RefCo", "highlight": "x"},
                               "dedupe": {"verdict": "new"}, "approved": None}))
    r = client.post("/api/proposal/apply", data={"file": str(pf)})
    assert r.status_code == 200 and r.json().get("referral_matches") == 1
    tl = (tmp_path / "ws" / "18-companies" / "RefCo" / "timeline.jsonl").read_text(encoding="utf-8")
    assert "内推匹配" in tl and "Alice Chen" in tl and "触达草稿" in tl


def test_intake_apply_appends_projection(client, tmp_path, monkeypatch):
    """入池批准 → 新行立刻进投影，作战室不等下一轮全量 pull（2026-08-10 报障：
    自己贴的机会批准后 15 分钟内在 pipeline 看不到）。幂等：同行不重复追加。"""
    import json as _json
    from joblander import notion as notion_mod
    page = {"id": "new-row-1", "url": "https://notion.example/newrow", "properties": {
        "Company": {"type": "title", "title": [{"plain_text": "FreshCo"}]},
        "Status": {"type": "status", "status": {"name": "Added"}}}}
    monkeypatch.setattr(notion_mod.NotionClient, "_request",
                        lambda self, *a, **k: page)
    pf = tmp_path / "ws" / "12-intake" / "fresh.json"
    pf.write_text(_json.dumps({"kind": "lead.intake",
                               "lead": {"company": "FreshCo", "highlight": "x"},
                               "dedupe": {"verdict": "new"}, "approved": None}))
    assert client.post("/api/proposal/apply", data={"file": str(pf)}).status_code == 200
    proj = _json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    fresh = [x for x in proj["rows"] if x.get("Company") == "FreshCo"]
    assert len(fresh) == 1 and fresh[0]["Status"] == "Added"
    from joblander.applyops import _append_projection
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws")}, path=tmp_path / "c.yaml")
    _append_projection(cfg, page)                     # 同 page 再喂一次
    proj2 = _json.loads((tmp_path / "ws" / "09-projections" / "tracker.json").read_text())
    assert len([x for x in proj2["rows"] if x.get("Company") == "FreshCo"]) == 1


def test_company_referral_endpoint(client, tmp_path, monkeypatch):
    """存量公司手动补跑内推匹配；无地图任务失败不炸系统。"""
    import json as _json
    (tmp_path / "ws" / "04-pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ws" / "04-pipeline" / "referral-map.md").write_text(
        "## Acme AI\n- Bob（校友，Acme infra TL）", encoding="utf-8")

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            return _json.dumps({"matches": [{"name": "Bob", "why": "infra TL", "channel": "linkedin"}],
                                "second_degree": [], "blind_spot": "", "outreach_draft": "Hi Bob…"})
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    r = client.post("/api/company/referral", data={"page_id": "aaa111"})
    assert r.json()["ok"] is True
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "内推匹配" in t["label"] for t in tasks)
    co = client.get("/company/aaa111").text
    assert "内推匹配" in co and "Bob" in co


def test_comp_research_endpoint(client, tmp_path, monkeypatch):
    """W4 端点：任务化出报告，参谋部列表可见、/comp 路由可读。"""
    monkeypatch.setattr("joblander.sourcing.mcf_search", lambda kw, limit=30: [
        {"uuid": "x1", "title": "AI Engineer", "postedCompany": {"name": "A"},
         "salary": {"minimum": 9000, "maximum": 13000,
                    "type": {"salaryType": "Monthly"}}}])

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            return "## 市场概览\n样本虽小，方向清晰。"
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    r = client.post("/api/comp/research", data={"keywords": "AI Engineer"})
    assert r.json()["ok"] is True
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "薪酬调研" in t["label"] for t in tasks)
    reports = list((tmp_path / "ws" / "15-comp").glob("comp-*.md"))
    assert reports
    pb = client.get("/playbook").text
    assert "薪酬调研" in pb and reports[0].name in pb
    doc = client.get(f"/comp/{reports[0].name}").text
    assert "市场概览" in doc and "SGD/月" in doc


def test_research_endpoint_zero_input_deep_mode(client, tmp_path, monkeypatch):
    """零输入调研 → 尽调员：简介+编号来源落时间线，dossier 落盘。"""
    import json as _json
    monkeypatch.setattr("joblander.search.web_search", lambda c, q, max_results=4: [
        {"title": "About", "url": "https://acme.example/about", "snippet": ""}])
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Acme AI enterprise agents. " * 50)

    class L:
        def __init__(self): self.n = 0
        def generate(self, prompt, system=None, json_mode=False):
            self.n += 1
            if self.n == 1:
                return _json.dumps({"queries": ["Acme AI"]})
            if self.n == 2:
                return _json.dumps({"thought": "已覆盖", "coverage": {}, "queries": []})
            return _json.dumps({"summary_md": "Acme 做企业 agent 平台 [1]。",
                                "facts": [], "salary_signals": [], "risks": [],
                                "gaps": []})
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    r = client.post("/api/company/research", data={"page_id": "aaa111"})
    assert r.json()["ok"] is True
    tasks = client.get("/api/tasks").json()
    assert any(t["status"] == "done" and "尽调" in t["label"] for t in tasks)
    co = client.get("/company/aaa111").text
    assert "尽调报告：公司综合简介" in co
    assert "acme.example/about" in co                      # 来源链接上了时间线
    assert (tmp_path / "ws" / "14-dossiers" / "Acme-AI.json").exists()


def test_md_to_html_inline_links():
    """[text](url) 渲染为可点链接（Deep Research 来源列表依赖）。"""
    from joblander.web.app import md_to_html
    h = md_to_html("1. [Helios Asia](https://en.wikipedia.org/wiki/Helios_Asia)（搜索摘要）")
    assert '<a href="https://en.wikipedia.org/wiki/Helios_Asia"' in h
    assert 'target="_blank"' in h and ">Helios Asia</a>" in h


def test_entry_delete_and_tombstone(client, tmp_path):
    """事件删除：本地条目物理删；(date,title) 墓碑防 Notion 合并流带回。"""
    import json as _json
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws"), "notion": {"token": "x"}},
                 path=tmp_path / "c.yaml")
    e = cf.timeline_add(cfg, "Acme AI", kind="note", title="Deep Research：公司综合简介",
                        content_md="dup1")
    r = client.post("/api/company/entry/delete",
                    data={"page_id": "aaa111", "entry_id": e["id"]})
    assert r.json()["ok"] is True
    assert all(x["id"] != e["id"] for x in cf.local_entries(cfg, "Acme AI"))
    body = f"### {e['date']} Deep Research：公司综合简介\n\n又回来了"
    merged = cf.merged_timeline(cfg, "Acme AI", notion_body=body)
    assert all("又回来了" not in (x.get("content_md") or "") for x in merged)  # 墓碑生效
    co = client.get("/company/aaa111").text
    assert "🗑 删除" in co                                     # UI 入口在


def test_research_upsert_no_duplicates_and_migrates_old_title(client, tmp_path, monkeypatch):
    """尽调重跑更新同一条目；改名前的「Deep Research」老条目就地换新名，不堆重复。"""
    import json as _json
    from joblander import company as cf
    from joblander.config import Config
    cfg = Config(raw={"workspace_dir": str(tmp_path / "ws"), "notion": {"token": "x"}},
                 path=tmp_path / "c.yaml")
    cf.timeline_add(cfg, "Acme AI", kind="note", title="Deep Research：公司综合简介",
                    content_md="旧版产物", author="ai", source="researcher")

    monkeypatch.setattr("joblander.search.web_search", lambda c, q, max_results=4: [
        {"title": "About", "url": "https://acme.example/about", "snippet": ""}])
    monkeypatch.setattr("joblander.researcher.fetch_url",
                        lambda u, timeout=20: "Acme AI enterprise agents. " * 50)

    class L:
        def __init__(self): self.n = 0
        def generate(self, prompt, system=None, json_mode=False):
            self.n += 1
            if json_mode and self.n % 3 == 1:
                return _json.dumps({"queries": ["Acme AI"]})
            if json_mode and self.n % 3 == 2:
                return _json.dumps({"thought": "覆盖", "coverage": {}, "queries": []})
            return _json.dumps({"summary_md": f"**这家公司是谁** v{self.n} [1]。",
                                "facts": [], "salary_signals": [], "risks": [], "gaps": []})
    monkeypatch.setattr("joblander.llm.from_config", lambda cfg, tier="pro": L())
    client.post("/api/company/research", data={"page_id": "aaa111"})
    client.post("/api/company/research", data={"page_id": "aaa111"})
    entries = cf.local_entries(cfg, "Acme AI")
    dr = [e for e in entries if (e.get("title") or "").startswith(("尽调", "Deep Research"))]
    assert len(dr) == 1                                        # 老条目 + 两跑 = 仍一条
    assert dr[0]["title"] == "尽调报告：公司综合简介"           # 就地改名
    assert "旧版产物" not in dr[0]["content_md"]


def test_arsenal_delete_and_reorder(client):
    """弹药库：删段（内部规则段拒删）+ 拖拽排序落库（内部段自动垫底）。"""
    import joblander.arsenal as ars
    from joblander.config import load_config as _lc     # client fixture 已打桩 cfg
    html = client.get("/arsenal").text
    assert "⠿" in html and "arsDel" in html

    r = client.post("/api/arsenal/add", data={"title": "临时段 X", "body": "- 一条"})
    assert r.json()["ok"]
    secs = client.get("/arsenal").text
    assert "临时段 X" in secs

    # 排序：把 临时段 X 提到最前
    from joblander.web.app import load_config
    cfg = load_config()
    data = ars.load_sections(cfg)
    normal = [s["title"] for s in data["sections"] if not s["internal"]]
    new_order = ["临时段 X"] + [t for t in normal if t != "临时段 X"]
    import json as _j
    r = client.post("/api/arsenal/reorder", data={"titles": _j.dumps(new_order)})
    assert r.json()["ok"]
    assert [s["title"] for s in ars.load_sections(cfg)["sections"]][0] == "临时段 X"
    assert ars.load_sections(cfg)["sections"][-1]["internal"] is True     # 规则仍垫底

    # 旧清单（缺新段）拒绝——防旧页面覆盖
    stale = client.post("/api/arsenal/reorder", data={"titles": _j.dumps(normal[:1])})
    assert stale.status_code == 400

    # 删除：正常段可删；内部段拒删
    idx = next(i for i, s in enumerate(ars.load_sections(cfg)["sections"])
               if s["title"] == "临时段 X")
    r = client.post("/api/arsenal/delete", data={"idx": idx, "title": "临时段 X"})
    assert r.json()["ok"]
    assert "临时段 X" not in client.get("/arsenal").text
    internal_idx = next(i for i, s in enumerate(ars.load_sections(cfg)["sections"])
                        if s["internal"])
    bad = client.post("/api/arsenal/delete",
                      data={"idx": internal_idx,
                            "title": ars.load_sections(cfg)["sections"][internal_idx]["title"]})
    assert bad.status_code == 400 and "内部规则段" in bad.json()["error"]
