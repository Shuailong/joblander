"""joblander Web（P2）— FastAPI 壳包住引擎：浏览器完成日常全部操作。

安全模型：默认只绑 127.0.0.1；所有写操作沿用提案制——UI 上的「批准」=人工审批动作。
UI v2 铁律（对着 Lucas 2026-08-07 的反馈定的）：
1. 面向用户不面向系统——入口按「他在干什么」放（公司页/看板/审批），不按模块放；
2. 公司档案页是主战场——结构化卡片 + 战役时间线，AI 产物与人写内容必须可分辨；
3. 工具不单独成页——动作长在它被需要的地方（全局两个 modal + 页面内按钮）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from joblander import company as companyfile
from joblander.applyops import apply_proposal, list_pending, reject_proposal
from joblander.config import load_config
from joblander.eventlog import EventLog

SGT = timezone(timedelta(hours=8))
HERE = Path(__file__).parent
# 本机名字白名单：Host 校验（挡 DNS rebinding）与写操作的 Origin 校验共用
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
ACTIVE = {"Added", "Dream", "In Consideration", "To Apply", "Screening Called",
          "Applied", "Interview Scheduled", "Interview Completed"}

# 看板列：名称 / 归入该列的状态 / 拖入该列落到的状态（空 = 拖入时弹状态选择）
BOARD = [
    ("线索", ["Added", "Dream"], "Added"),
    ("评估中", ["In Consideration"], "In Consideration"),
    ("待申请", ["To Apply"], "To Apply"),
    ("申请 / 初筛", ["Applied", "Screening Called"], "Applied"),
    ("面试", ["Interview Scheduled", "Interview Completed"], "Interview Scheduled"),
    ("Offer", ["Offer Received"], "Offer Received"),
    ("关闭", ["Rejected", "Terminated", "Withdrawn", "Not Apply"], ""),
]


def md_to_html(text: str) -> str:
    """极简 markdown → HTML（标题/列表/粗体/引用/表格）——够 brief/报告/素材库用。"""
    import html as _h
    import re as _re
    out: list[str] = []
    in_ul = in_tbl = False
    tbl_head = True

    def _close():
        nonlocal in_ul, in_tbl
        if in_ul: out.append("</ul>"); in_ul = False
        if in_tbl: out.append("</table>"); in_tbl = False

    for line in (text or "").splitlines():
        s = _h.escape(line.rstrip())
        s = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = _re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                    r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        if s.startswith("|"):
            if in_ul: out.append("</ul>"); in_ul = False
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            if cells and all(_re.fullmatch(r":?-+:?", c) for c in cells):
                continue                                  # 表头分隔行 |---|---|
            if not in_tbl:
                out.append("<table>"); in_tbl = True; tbl_head = True
            tag = "th" if tbl_head else "td"
            out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            tbl_head = False
            continue
        if in_tbl: out.append("</table>"); in_tbl = False
        if s.startswith("```"):
            if in_ul: out.append("</ul>"); in_ul = False
            out.append(f'<div class="mono-line">{s.replace("```", "")}</div>'); continue
        if s.startswith("- "):
            if not in_ul: out.append("<ul>"); in_ul = True
            out.append(f"<li>{s[2:]}</li>"); continue
        if in_ul: out.append("</ul>"); in_ul = False
        if _re.fullmatch(r"-{3,}|\*{3,}", s.strip()): out.append("<hr>")
        elif s.startswith("### "): out.append(f"<h4>{s[4:]}</h4>")
        elif s.startswith("## "): out.append(f"<h3>{s[3:]}</h3>")
        elif s.startswith("# "): out.append(f"<h2>{s[2:]}</h2>")
        elif s.startswith("&gt; "): out.append(f'<div class="q">{s[5:]}</div>')
        elif not s.strip(): out.append("<div class='gap'></div>")
        else: out.append(f"<p>{s}</p>")
    _close()
    return "\n".join(out)


# ---------- 后台任务（长 LLM 作业不锁页面：托盘可见、切页不丢、完成即提醒） ----------
TASKS: dict[str, dict] = {}     # 内存注册表：产物全部落盘，状态可丢（重启即清）


def start_task(kind: str, label: str, fn) -> str:
    import os
    import threading
    import time
    import uuid
    tid = uuid.uuid4().hex[:8]
    TASKS[tid] = {"id": tid, "kind": kind, "label": label, "status": "running",
                  "started": time.time(), "result": None, "error": ""}

    def run():
        try:
            TASKS[tid]["result"] = fn()
            TASKS[tid]["status"] = "done"
        except Exception as e:
            TASKS[tid]["error"] = str(e)
            TASKS[tid]["status"] = "error"
            # TASKS 是内存注册表，失败条目 120 秒后就从 /api/tasks 消失、重启即清空。
            # 不落盘的话，一次失败的生成除了当时那个红字提示，事后再无任何痕迹可查。
            try:                       # start_task 是模块级函数，失败路径上现取 cfg
                from joblander.config import load_config as _lc
                EventLog(_lc().workspace_dir / "08-events" / "event-log.jsonl").append(
                    "task.failed", "web", {"kind": kind, "label": label,
                                           "error": str(e)[:300]})
            except Exception:
                pass
        TASKS[tid]["ended"] = time.time()

    if os.environ.get("JOBLANDER_TASKS_SYNC"):    # 测试/脚本：内联执行同一条链路
        run()
    else:
        threading.Thread(target=run, daemon=True, name=f"task-{kind}").start()
    return tid


def recent_tasks() -> list[dict]:
    import time
    now = time.time()
    out = []
    for t in TASKS.values():
        if t["status"] == "running" or now - t.get("ended", now) < 120:
            out.append({k: t[k] for k in ("id", "kind", "label", "status", "error")}
                       | {"secs": int(now - t["started"])})
    return sorted(out, key=lambda t: -t["secs"])


GREETINGS = {
    "dawn": ["早。天还没全亮，你已经在阵地上了。", "清晨好。先吃早饭，仗不急这一口。"],
    "morning": ["早上好。今天挑一件最重要的，先打它。", "早上好。节奏在你手里，不在收件箱里。",
                "早上好。一次只打一场，把每一场打好。"],
    "noon": ["中午好。吃口好的，战线不会跑。", "中午了。休整也是备战的一部分。"],
    "afternoon": ["下午好。稳住节奏，一步是一步。", "下午好。做过的每一件，都会算数。",
                  "下午好。困了就起来走两步，回来接着打。"],
    "evening": ["晚上好。今天推进的，都记在档案里了。", "晚上好。收个尾，把今天写下来。",
                "晚上好。每发出去的一枪都在积累势能。"],
    "night": ["夜深了。看一眼就去睡，明天还有仗要打。", "深夜了。休息也是战斗力。"],
}


def greeting(now: datetime) -> str:
    import random
    h = now.hour
    slot = ("dawn" if 5 <= h < 8 else "morning" if 8 <= h < 12
            else "noon" if 12 <= h < 14 else "afternoon" if 14 <= h < 18
            else "evening" if 18 <= h < 23 else "night")
    return random.choice(GREETINGS[slot])


def create_app(with_daemon: bool = True) -> FastAPI:
    from contextlib import asynccontextmanager

    cfg = load_config()
    daemon = None

    @asynccontextmanager
    async def lifespan(_app):
        nonlocal daemon
        if with_daemon:
            from joblander.daemon import Daemon
            daemon = Daemon(cfg)
            daemon.start_background()
        yield
        if daemon:
            daemon.stop()

    app = FastAPI(title="joblander", lifespan=lifespan)

    @app.middleware("http")
    async def _same_origin_guard(request, call_next):
        """本地单用户 app 没有登录态，绑 127.0.0.1 只挡住网络访问，挡不住浏览器：
        用户随便开一个网页，那页就能向 127.0.0.1 提交表单（简单请求无预检），
        命中任何写接口——包括 /api/drill/run 那条「跑用户代码」的路径。

        两道闸：
        - Host 必须是本机名字，挡 DNS rebinding（恶意域名解析到 127.0.0.1 后
          浏览器会带上它自己的 Host，读接口同样要挡，所以这道对所有方法生效）
        - 写方法（POST/PUT/PATCH/DELETE）的 Origin/Referer 必须是本站。
          跨站表单提交浏览器一定带 Origin；两个头都没有的是 curl/CLI/测试，放行。
        """
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host and host not in _LOCAL_HOSTS:
            return JSONResponse({"error": f"拒绝：Host「{host}」不是本机"}, status_code=421)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            src = request.headers.get("origin") or request.headers.get("referer") or ""
            if src:
                try:
                    h = urlparse(src).hostname or ""
                except ValueError:
                    h = "?"
                if h not in _LOCAL_HOSTS:
                    return JSONResponse(
                        {"error": "拒绝：跨站请求（joblander 只接受本机页面发起的写操作）"},
                        status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def _no_cache_html(request, call_next):
        resp = await call_next(request)
        if (resp.headers.get("content-type") or "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-cache"    # 页面永远向服务器要新（静态资源有 ?v=）
        return resp

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    tpl.env.filters["md"] = md_to_html
    tpl.env.filters["atticon"] = companyfile.attachment_icon
    # 静态资源版本号（进程启动时间戳）：改了 css/js 重启即生效，不吃浏览器缓存的旧文件
    tpl.env.globals["v"] = datetime.now(SGT).strftime("%m%d%H%M%S")

    def _rows():
        """战线投影；还没有就是空战线，不是错误——Notion 是可选集成（README），
        纯本地用户永远不会跑 pull，此前首页/作战室/Playbook 直接 500 打不开。"""
        from joblander.prep import _load_projection
        try:
            return _load_projection(cfg)
        except FileNotFoundError:
            return []

    def _row_by_pid(page_id: str):
        for r in _rows():
            if (r.get("notion_page_id") or "").replace("-", "") == page_id.replace("-", ""):
                return r
        return None

    def _log() -> EventLog:
        return EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl")

    def _llm(tier: str = "pro"):
        from joblander.llm import from_config
        return from_config(cfg, tier)

    def _notion():
        """没配 Notion 返回 None——下游全部接受 None（mine_jd / build_capability）。
        此前无条件取 cfg.raw["notion"]["token"]，纯本地用户点「生成定制简历」和
        「重估能力画像」都只拿到 error: 'notion'。同一类 bug 在 applyops 修过，
        这个调用点漏了。"""
        from joblander.notion import NotionClient, notion_configured
        return NotionClient(cfg.raw["notion"]["token"]) if notion_configured(cfg) else None

    def _split_pending(pending):
        """提案按属地拆：面后与跟进→公司页；入池→新机会；日记与排期缺口→指挥中心。"""
        return {"scribe": [p for p in pending if "field_diffs" in p],
                "lead": [p for p in pending if p.get("kind") == "lead.intake"],
                "diary": [p for p in pending if p.get("kind") == "diary.entry"],
                "calendar": [p for p in pending if p.get("kind") == "calendar.event"]}

    def ctx(nav: str, **kw):
        """所有页面共享的上下文：两枚角标随处可见——今天=待批更新，新机会=待入池。"""
        parts = _split_pending(list_pending(cfg))
        kw["nav"] = nav
        kw.setdefault("pending_n", len(parts["scribe"]) + len(parts["diary"])
                      + len(parts["calendar"]))
        kw.setdefault("leads_n", len(parts["lead"]))
        np = ""
        try:                                     # 侧栏「同步 Notion」标上次拉取时间
            v = str(json.loads((cfg.workspace_dir / "08-events" / "daemon-state.json")
                               .read_text(encoding="utf-8")).get("last.notion_pull") or "")
            today = datetime.now(SGT).strftime("%Y-%m-%d")
            np = v[11:16] if v[:10] == today else (v[5:10] + " " + v[11:16] if v else "")
        except Exception:
            pass
        kw.setdefault("notion_pulled", np)
        return kw

    # ---------- 页面 ----------

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        rows = _rows()
        today = datetime.now(SGT).strftime("%Y-%m-%d")
        active = [r for r in rows if r.get("Status") in ACTIVE]
        overdue = [r for r in active if (r.get("Follow-up Reminder") or "9999") < today]
        due = [r for r in active if r.get("Follow-up Reminder") == today]
        high = [r for r in active if r.get("Priority") == "High"]
        pending = list_pending(cfg)
        parts = _split_pending(pending)
        now = datetime.now(SGT)
        cal_events: list[dict] = []
        cal_stale = True
        fresh: dict[str, str] = {}
        sp = cfg.workspace_dir / "08-events" / "daemon-state.json"
        if sp.exists():
            try:
                state = json.loads(sp.read_text(encoding="utf-8"))
                cc = state.get("calendar_cache") or {}
                cal_events = cc.get("events", [])
                at = cc.get("at", "")
                cal_stale = (not at) or (now - datetime.fromisoformat(at)
                                         ).total_seconds() > 45 * 60
                for label, key in (("tracker", "last.notion_pull"),
                                   ("calendar", "last.calendar_watch"),
                                   ("gmail", "last.gmail_scan")):
                    v = str(state.get(key) or (at if label == "calendar" else ""))
                    fresh[label] = v[11:16] if len(v) >= 16 and v[:10] == today else \
                        (v[5:16].replace("T", " ") if v else "—")
            except Exception:
                pass
        # 近 4 天场次：只看面试相关——kind 判定（标题关键词）+ 活跃公司名命中双腿，
        # 「Chat with Kai @ Nimbus」这类无关键词标题靠公司名兜底；私人日程不上指挥中心
        co_names = [c for c in ((r.get("Company") or "").split("（")[0].split("(")[0]
                                .strip().casefold() for r in active) if len(c) >= 2]

        def _battle_ev(e):
            if e.get("kind") == "interview":
                return True
            t = str(e.get("title") or "").casefold()
            return any(c in t for c in co_names)

        day_label = ["今天", "明天", "后天"]
        cal_days = []
        for i in range(4):
            d = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            evs = sorted([e for e in cal_events if str(e.get("start", ""))[:10] == d
                          and _battle_ev(e)], key=lambda e: e.get("start", ""))
            if i == 0 or evs:
                wd = "周" + "一二三四五六日"[datetime.fromisoformat(d).weekday()]
                cal_days.append({"date": d, "label": day_label[i] if i < 3 else wd,
                                 "wd": wd, "events": evs, "is_today": i == 0})
        # 今日日记：素材（战线事件）→ 草稿提案（可编辑）→ 定稿在日报 → 手记随时写
        from joblander.daily import DIARY_HEADER, NOTES_HEADER, daily_path, read_section
        from joblander.diary import today_battle_events
        battles = today_battle_events(cfg, today)
        dp = daily_path(cfg, today)
        diary_final = read_section(dp, DIARY_HEADER)
        my_notes = read_section(dp, NOTES_HEADER)
        return tpl.TemplateResponse(request, "dashboard.html", ctx(
            "dash", today=today, rows=rows, active=active, overdue=overdue, due=due,
            high=high, pending=pending, greet=greeting(now),
            scribe_pending=parts["scribe"], lead_pending=parts["lead"],
            diary_pending=parts["diary"], cal_pending=parts["calendar"],
            cal_days=cal_days, cal_stale=cal_stale, fresh=fresh,
            battles=battles, diary_final=diary_final, my_notes=my_notes,
            daily_name=f"{today}.md"))

    @app.get("/pipeline", response_class=HTMLResponse)
    def pipeline(request: Request):
        rows = _rows()
        order = {"High": 0, "Medium": 1, "Low": 2, None: 3}
        rows = sorted(rows, key=lambda r: (order.get(r.get("Priority"), 3),
                                           r.get("Follow-up Reminder") or "9999"))
        today = datetime.now(SGT).strftime("%Y-%m-%d")
        # 哪家在等他动手：锚在该公司的待批提案 + 到期 follow-up（⚑ 标出来）
        parts = _split_pending(list_pending(cfg))
        todos: dict[str, int] = {}
        for p in parts["scribe"] + parts["calendar"]:
            pid = p.get("notion_page_id")
            if pid:
                todos[pid] = todos.get(pid, 0) + 1
        for r in rows:
            fu = r.get("Follow-up Reminder")
            if fu and fu <= today and r.get("Status") in ACTIVE:
                todos[r["notion_page_id"]] = todos.get(r["notion_page_id"], 0) + 1
        flags = {r["notion_page_id"] for r in rows
                 if companyfile.load_meta(cfg, r.get("Company") or "").get("my_flag")}
        board = []
        for name, statuses, primary in BOARD:
            cards = [r for r in rows if r.get("Status") in statuses]
            board.append({"name": name, "statuses": statuses, "primary": primary,
                          "rows": cards})
        return tpl.TemplateResponse(request, "pipeline.html", ctx(
            "pipe", rows=rows, board=board, today=today, todos=todos, flags=flags,
            active_n=sum(1 for r in rows if r.get("Status") in ACTIVE)))

    @app.get("/sourcing", response_class=HTMLResponse)
    def sourcing_page(request: Request):
        from joblander.scout import _name_tokens
        from joblander.sourcing import load_prefs, search_links
        leads = _split_pending(list_pending(cfg))["lead"]
        glist: list[dict] = []
        for p in leads:
            name = (p.get("lead") or {}).get("company") or "公司未披露"
            qt = _name_tokens(name)
            # 同公司并组用与查重同一套归一化（BCG 简名与法人名要落同一组）
            g = next((g for g in glist if qt and g["tokens"]
                      and (qt <= g["tokens"] or g["tokens"] <= qt)), None)
            if g is None:
                g = {"company": name, "tokens": qt, "items": [], "best": 0}
                glist.append(g)
            else:
                g["tokens"] = g["tokens"] | qt
                if len(name) < len(g["company"]):
                    g["company"] = name          # 短名通常是干净的显示名
            g["items"].append(p)
            g["best"] = max(g["best"], ((p.get("fit") or {}).get("fit")) or 0)
        for g in glist:
            g["items"].sort(key=lambda p: -(((p.get("fit") or {}).get("fit")) or 0))
        ordered = sorted(glist, key=lambda g: -g["best"])
        good = [g for g in ordered if g["best"] >= 3]
        low = [g for g in ordered if g["best"] < 3]
        prefs = load_prefs(cfg)
        state = {}
        sp = cfg.workspace_dir / "08-events" / "daemon-state.json"
        if sp.exists():
            try:
                state = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        mcf_last = next((e for e in reversed(list(_log().events()))
                         if e["kind"] == "sourcing.mcf_run"), None)
        bankp = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
        bank = {"exists": bankp.exists(),
                "kb": round(bankp.stat().st_size / 1024) if bankp.exists() else 0,
                "mtime": datetime.fromtimestamp(bankp.stat().st_mtime, SGT)
                         .strftime("%Y-%m-%d") if bankp.exists() else ""}
        profile_files = []
        for rel in (cfg.raw.get("profile", {}).get("files") or []):
            p = cfg.workspace_dir / rel
            profile_files.append({
                "name": Path(rel).name, "rel": rel, "exists": p.exists(),
                "kb": round(p.stat().st_size / 1024) if p.exists() else 0,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime, SGT)
                         .strftime("%Y-%m-%d") if p.exists() else ""})
        from joblander.sourcing import _profile_digest
        return tpl.TemplateResponse(request, "sourcing.html", ctx(
            "src", good=good, low=low, total=len(leads), prefs=prefs,
            links=search_links(prefs), profile_files=profile_files, bank=bank,
            digest_chars=len(_profile_digest(cfg)),
            gmail_last=(state.get("last.gmail_scan") or "")[:16].replace("T", " "),
            mcf_last=mcf_last))

    @app.get("/company/{page_id}", response_class=HTMLResponse)
    def company_page(request: Request, page_id: str):
        row = _row_by_pid(page_id)
        if row is None:
            return HTMLResponse("未找到该行", status_code=404)
        name = row.get("Company") or ""
        meta = companyfile.load_meta(cfg, name)
        today_str = datetime.now(SGT).strftime("%Y-%m-%d")
        fu = row.get("Follow-up Reminder")
        due_today = bool(fu) and fu <= today_str and row.get("Status") in ACTIVE
        try:                       # 附件是事件的属性：游离附件按文件名日期绑回（幂等自愈）
            orphans = companyfile.bind_orphan_attachments(cfg, name)
        except Exception:
            orphans = []
        # 时间线只读本地档案（2026-08-10 定案）：Notion 不再做内容同步，页面留链接
        timeline = companyfile.merged_timeline(cfg, name)
        tl_groups: list[dict] = []
        for e in timeline:
            d = e.get("date") or ""
            if tl_groups and tl_groups[-1]["date"] == d:
                tl_groups[-1]["entries"].append(e)
            else:
                try:
                    wd = "一二三四五六日"[datetime.fromisoformat(d).weekday()]
                except Exception:
                    wd = ""
                tl_groups.append({"date": d, "weekday": wd, "entries": [e]})
        slug = companyfile.slugify(name)
        research = None
        research_summary_html = ""
        rp = companyfile.dossier_path(cfg, name)
        if rp.exists():
            try:
                research = json.loads(rp.read_text(encoding="utf-8"))
                if research.get("summary_md"):
                    research_summary_html = md_to_html(research["summary_md"])
            except Exception:
                research = None
        pid_norm = (row.get("notion_page_id") or "").replace("-", "")
        props = [p for p in _split_pending(list_pending(cfg))["scribe"]
                 if (p.get("notion_page_id") or "").replace("-", "") == pid_norm]
        from joblander.resume_agent import resume_dir, resume_state
        rstate = resume_state(cfg, name)
        rbase = ""
        if rstate.get("versions"):
            rbase = str(resume_dir(cfg, name).relative_to(cfg.workspace_dir))
        # 匹配雷达：JD 定制轴（评估产出 radar：轴/demand/self 全部按该 JD 提炼）；
        # 老数据（dim_demand，画像轴）兼容渲染
        from joblander.capability import load_capability
        cap_dims = load_capability(cfg).get("dimensions") or []
        rd = (meta.get("assessment") or {}).get("radar") or []
        if rd:
            match_radar = [{"name": x.get("axis", ""), "market": x.get("demand", 0),
                            "self": x.get("self", 0), "basis": x.get("basis", "")}
                           for x in rd]
        else:
            dd = {x.get("name"): x for x in
                  (meta.get("assessment") or {}).get("dim_demand") or []}
            match_radar = [{"name": d["name"],
                            "market": (dd.get(d["name"]) or {}).get("demand", 0),
                            "self": d.get("self") or 0}
                           for d in cap_dims] if dd else []
        from joblander.resume_chat import load_chat
        # 简历卡单线程：对话轮次 + 版本发布事件按时间合流——历史即对话，没有第二个列表。
        # 默认视野 = 最新版本起的一段；更早的折叠成历史
        rthread = sorted(
            [*load_chat(cfg, row["Company"]),
             *[{**v, "role": "version"} for v in rstate.get("versions") or []]],
            key=lambda t: t.get("at") or "")
        last_v = max((i for i, t in enumerate(rthread) if t.get("role") == "version"),
                     default=-1)
        # 阶段流转图：复用看板列（BOARD 即唯一阶段模型）——主线六段推进，
        # 关闭列不在主线上，是任一阶段都可能转入的岔道
        cur = (row.get("Status") or "").strip()
        hit = next((i for i, (_, sts, _) in enumerate(BOARD[:-1]) if cur in sts), -1)
        flow_stages = [{"label": lbl,
                        "hint": " ⇄ ".join(sts) + "（多轮往复）" if lbl == "面试"
                                else " / ".join(sts),
                        "statuses": sts,
                        "state": "done" if i < hit else "cur" if i == hit else ""}
                       for i, (lbl, sts, _) in enumerate(BOARD[:-1])]
        return tpl.TemplateResponse(request, "company.html", ctx(
            "pipe", r=row, meta=meta, timeline=timeline, tl_groups=tl_groups,
            flow_stages=flow_stages, flow_closed=cur in BOARD[-1][1],
            rthread_old=rthread[:last_v] if last_v > 0 else [],
            rthread_new=rthread[last_v:] if last_v >= 0 else rthread,
            orphans=orphans,
            today=today_str, due_today=due_today,
            has_cap=bool(cap_dims),
            props=props,
            jd_files=companyfile.list_files(cfg, name, "jd"),
            assessment=meta.get("assessment"),
            rstate=rstate, rbase=rbase, match_radar=match_radar,
            intake=companyfile.intake_date(cfg, row),
            research=research, research_summary_html=research_summary_html,
            kind_labels=companyfile.KIND_LABELS))

    @app.get("/inbox")
    def inbox_gone():
        """审批页已解散（UI v2.1）：提案长在属地——公司页/机会页/今天页。"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/", status_code=302)

    @app.get("/system", response_class=HTMLResponse)
    def system(request: Request):
        log = _log()
        now = datetime.now(SGT)
        cutoff24 = (now - timedelta(hours=24)).isoformat()
        kinds: dict[str, int] = {}
        n = 0
        fails24 = 0
        for e in log.events():
            n += 1
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            if e["kind"] == "job.failed" and e["ts"] >= cutoff24:
                fails24 += 1
        rules = cfg.sentinel_rules
        checks = cfg.raw.get("sentinel", {}).get("judgment_checks", [])
        from joblander.applyops import notion_write_enabled

        state = {}
        spath = cfg.workspace_dir / "08-events" / "daemon-state.json"
        if spath.exists():
            try:
                state = json.loads(spath.read_text(encoding="utf-8"))
            except Exception:
                state = {}

        def _age_ok(iso: str, limit_min: int) -> bool:
            try:
                return (now - datetime.fromisoformat(iso)).total_seconds() <= limit_min * 60
            except Exception:
                return False

        jobs = []
        for key, label, limit in [("calendar_watch", "日历哨兵（今日场次 + T-24h/T-2h 弹药）", 70),
                                  # daemon 写的是 last.notion_pull（首页「同步 Notion」也读它）；
                                  # 这里原先查 last.notion_diff_pull——一个谁都不写的 key，
                                  # 于是这行健康度在配置完好的情况下也永远显示「未跑」。
                                  ("notion_pull", "Notion 回流 diff", 40),
                                  ("gmail_scan", "Gmail 扫描（含 Job Alert）", 70)]:
            last = state.get(f"last.{key}") or ""
            jobs.append({"label": label, "last": last[:16].replace("T", " ") or "未跑",
                         "ok": _age_ok(last, limit)})
        for key, label in [("sourcing", "夜扫 MCF（02:30）"), ("morning", "晨报（08:15）"),
                           ("diary", "日记草稿（21:30）"), ("weekly", "周报（周日 20:00）")]:
            d = state.get(f"done.{key}") or ""
            jobs.append({"label": label, "last": d or "未跑", "ok": bool(d)})

        creds = []
        for fn, label in [("gmail_token.json", "Gmail（只读 OAuth）"),
                          ("calendar_token.json", "Google Calendar（读 + 确认写）")]:
            p = cfg.workspace_dir / ".credentials" / fn
            creds.append({"label": label, "ok": p.exists(),
                          "note": "已连接" if p.exists() else "未连接"})
        creds.append({"label": "Notion API", "ok": bool(cfg.raw.get("notion", {}).get("token")),
                      "note": "已配置" if cfg.raw.get("notion", {}).get("token") else "未配置"})
        creds.append({"label": "MyCareersFuture", "ok": True, "note": "公开 API，无需凭证"})

        return tpl.TemplateResponse(request, "system.html", ctx(
            "sys", total_events=n,
            kinds=sorted(kinds.items(), key=lambda kv: -kv[1]),
            rules=rules, checks=checks, notion_write=notion_write_enabled(cfg),
            jobs=jobs, creds=creds, fails24=fails24))

    @app.get("/briefs")
    def briefs_gone():
        """弹药库已解散（UI v2.1）：brief 是「为该公司下一步做的准备」，长在公司页备战区。"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/", status_code=302)

    @app.get("/company/{page_id}/entry/{entry_id}", response_class=HTMLResponse)
    def entry_view(request: Request, page_id: str, entry_id: str):
        """时间线事件的全屏阅读页——通用：任何带正文的本地事件都能整篇读。"""
        row = _row_by_pid(page_id)
        if row is None:
            return HTMLResponse("行不存在", status_code=404)
        e = next((x for x in companyfile.local_entries(cfg, row["Company"])
                  if x.get("id") == entry_id), None)
        if e is None:
            return HTMLResponse("事件不存在", status_code=404)
        kind_label = companyfile.KIND_LABELS.get(e.get("kind"), e.get("kind") or "")
        head = (f'<div class="note" style="margin-bottom:12px">'
                f'{e.get("date")} · {kind_label} · '
                f'{"AI 产出" if e.get("author") == "ai" else "人工"} · '
                f'<a href="/company/{page_id}#tl">← 回 {row["Company"]} 时间线</a></div>')
        mr = e.get("my_review") or {}
        return tpl.TemplateResponse(request, "doc.html", ctx(
            "pipe", title=f'{e.get("title")} · {row["Company"]}',
            html=head + md_to_html(e.get("content_md") or e.get("summary") or "（无正文）"),
            rev_pid=page_id, rev_eid=entry_id,
            rev_text=mr.get("text", ""), rev_updated=(mr.get("updated") or "")[:10]))

    @app.get("/briefs/{name}", response_class=HTMLResponse)
    def brief_view(request: Request, name: str):
        p = cfg.workspace_dir / "10-briefs" / name
        if not p.exists() or ".." in name:
            return HTMLResponse("not found", status_code=404)
        return tpl.TemplateResponse(request, "doc.html", ctx(
            "pipe", title=name, html=md_to_html(p.read_text(encoding="utf-8"))))

    @app.get("/comp/{name}", response_class=HTMLResponse)
    def comp_view(request: Request, name: str):
        p = cfg.workspace_dir / "15-comp" / name
        if not p.exists() or ".." in name:
            return HTMLResponse("not found", status_code=404)
        return tpl.TemplateResponse(request, "doc.html", ctx(
            "pb", title=name, html=md_to_html(p.read_text(encoding="utf-8"))))

    @app.post("/api/comp/research")
    def api_comp_research(keywords: str = Form(""), urls: str = Form(""),
                          notes: str = Form("")):
        """W4 薪酬调研：MCF 实时 band + 可选补充源 → 结构化带日期报告（任务化）。"""
        kw_list = [k.strip() for k in keywords.replace("，", ",").split(",") if k.strip()]
        url_list = [u.strip() for u in urls.splitlines() if u.strip().startswith("http")]

        def run():
            from joblander.compensation import build_comp_report
            out = build_comp_report(cfg, _llm(), keywords=kw_list or None,
                                    extra_urls=url_list, notes=notes)
            return {"report": out.name}

        tid = start_task("comp", "薪酬调研（W4）", run)
        return {"ok": True, "task": tid}

    @app.get("/playbook", response_class=HTMLResponse)
    def playbook_page(request: Request):
        from joblander.capability import load_capability
        from joblander.playbook import load as pb_load
        from joblander.weekly import playbook_health
        entries = pb_load(cfg)
        health = {h["id"]: h for h in playbook_health(cfg)}
        groups: dict[str, list] = {}
        for e in entries:
            groups.setdefault(e.get("category") or "未分组", []).append(e)
        ddir = cfg.workspace_dir / "13-daily"
        weeklies = sorted(ddir.glob("*weekly*.md"), reverse=True) if ddir.exists() else []
        dailies = sorted([f for f in ddir.glob("*.md") if "weekly" not in f.name],
                         reverse=True)[:14] if ddir.exists() else []
        bank = cfg.workspace_dir / "03-materials" / "achievement-bank.md"
        cap = load_capability(cfg)
        from joblander.capability import TERMINAL
        pool = sorted(({"company": (r.get("Company") or "").strip(),
                        "priority": r.get("Priority") or ""}
                       for r in _rows() if (r.get("Company") or "").strip()
                       and r.get("Status") not in TERMINAL),
                      key=lambda x: (x["priority"] != "High", x["company"]))
        scope = cap.get("jd_scope") or {"mode": "high", "companies": []}
        cdir = cfg.workspace_dir / "15-comp"
        comp_reports = sorted(cdir.glob("comp-*.md"), reverse=True)[:8] if cdir.exists() else []
        return tpl.TemplateResponse(request, "playbook.html", ctx(
            "pb", groups=groups, health=health, cap=cap, pool=pool, scope=scope,
            weeklies=[f.name for f in weeklies], dailies=[f.name for f in dailies],
            comp_reports=[f.name for f in comp_reports],
            has_bank=bank.exists()))

    @app.get("/arsenal", response_class=HTMLResponse)
    def arsenal_page(request: Request):
        from joblander.arsenal import load_sections
        data = load_sections(cfg)
        secs = [{**s, "html": md_to_html(s["body"])}
                for s in data["sections"] if not s["internal"]]
        internal_n = sum(1 for s in data["sections"] if s["internal"])
        # 简历版本：通用两版（03-materials 母版）+ 各公司定制版（ResumeCustomiserAgent 产出）
        # 母版按目录实际内容列，不写死文件名——原先钉死作者本人的两个 PDF 名字，
        # 别人的弹药库这一栏永远是空的。同名 .pdf 存在就一并挂上。
        generic = []
        mdir = cfg.workspace_dir / "03-materials"
        for hp in sorted(mdir.glob("resume*.html")) if mdir.exists() else []:
            pp = next((p for p in (hp.with_suffix(".pdf"), *mdir.glob(f"{hp.stem}*.pdf"))
                       if p.exists()), None)
            label = "标准版" if hp.name == "resume.html" else hp.stem.replace("resume-", "")
            generic.append({
                "label": label, "html": f"03-materials/{hp.name}",
                "pdf": f"03-materials/{pp.name}" if pp else "",
                "mtime": datetime.fromtimestamp(hp.stat().st_mtime, SGT)
                         .strftime("%Y-%m-%d")})
        return tpl.TemplateResponse(request, "arsenal.html", ctx(
            "ars", sections=secs, internal_n=internal_n, generic=generic,
            exists=bool(data["sections"] or data["preamble"])))

    @app.post("/api/arsenal/save")
    def api_arsenal_save(idx: int = Form(...), title: str = Form(...),
                         body: str = Form(...), orig_title: str = Form("")):
        from joblander.arsenal import save_section
        try:
            save_section(cfg, idx, title, body, orig_title=orig_title)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/arsenal/add")
    def api_arsenal_add(title: str = Form(...), body: str = Form(...)):
        from joblander.arsenal import add_section
        try:
            add_section(cfg, title, body)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/arsenal/delete")
    def api_arsenal_delete(idx: int = Form(...), title: str = Form(...)):
        from joblander.arsenal import delete_section
        try:
            delete_section(cfg, idx, title)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/arsenal/reorder")
    def api_arsenal_reorder(titles: str = Form(...)):
        """titles = JSON 数组（非内部段的完整新顺序）；内部规则段自动垫底。"""
        from joblander.arsenal import reorder_sections
        try:
            reorder_sections(cfg, json.loads(titles))
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.get("/drill", response_class=HTMLResponse)
    def drill_page(request: Request, id: str = "", skip: str = ""):
        from fastapi.responses import RedirectResponse

        from joblander.drill import get_problem, random_problem
        p = get_problem(id) if id else None
        if not p:
            # 随机出题后 302 定格到具体题——刷新不换题，草稿不丢
            return RedirectResponse(f"/drill?id={random_problem(exclude=skip)['id']}",
                                    status_code=302)
        return tpl.TemplateResponse(request, "drill.html", ctx("drill", p=p))

    @app.post("/api/drill/run")
    def api_drill_run(id: str = Form(...), code: str = Form(...)):
        from joblander.drill import run_drill
        out = run_drill(id, code)
        if not out.get("ok"):
            return JSONResponse({"error": out.get("error", "")}, status_code=400)
        return out

    @app.post("/api/capability/scope")
    def api_capability_scope(mode: str = Form(...), companies: str = Form("")):
        from joblander.capability import set_scope
        try:
            set_scope(cfg, mode, [c for c in companies.split("|") if c.strip()])
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/capability/override")
    def api_capability_override(name: str = Form(...), self_score: int = Form(...),
                                note: str = Form("")):
        from joblander.capability import set_override
        try:
            set_override(cfg, name, self_score, note)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/capability/rebuild")
    def api_capability_rebuild():
        from joblander.capability import build_capability
        tid = start_task("capability", "重估能力画像",
                         lambda: build_capability(cfg, _llm(), notion_client=_notion()))
        return {"ok": True, "task": tid, "label": "重估能力画像"}

    WSDOC_PREFIXES = ("03-materials/", "13-daily/", "15-offers/")

    @app.get("/wsdoc/{rel:path}", response_class=HTMLResponse)
    def wsdoc(request: Request, rel: str):
        """workspace 内白名单目录的 markdown 渲染视图（素材库/日报/周报/offer 矩阵）。"""
        if ".." in rel or not rel.endswith(".md") \
                or not rel.startswith(WSDOC_PREFIXES):
            return HTMLResponse("not found", status_code=404)
        p = cfg.workspace_dir / rel
        if not p.is_file():
            return HTMLResponse("not found", status_code=404)
        notes_name = ""
        notes = ""
        if rel.startswith("13-daily/"):               # 日报/周报：手记可在渲染页直接补
            from joblander.daily import NOTES_HEADER, read_section
            notes_name = Path(rel).name
            notes = read_section(p, NOTES_HEADER)
        return tpl.TemplateResponse(request, "doc.html", ctx(
            "pb", title=Path(rel).name,
            html=md_to_html(p.read_text(encoding="utf-8")),
            notes_name=notes_name, notes=notes))

    @app.get("/offers", response_class=HTMLResponse)
    def offers_page(request: Request):
        p = cfg.workspace_dir / "15-offers" / "offers.json"
        offers = []
        if p.exists():
            try:
                offers = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                offers = []
        snaps = []
        if offers:
            from joblander.offer import compare_offers
            try:
                snaps = compare_offers(cfg.policy, offers)
            except Exception as e:
                snaps = []
                _log().append("offers.compare_failed", "joblander.web", {"error": str(e)})
        return tpl.TemplateResponse(request, "offers.html",
                                    ctx("pipe", offers=offers, snaps=snaps))

    @app.get("/files/{rel:path}")
    def serve_file(rel: str):
        """档案附件/JD 的只读文件服务——限 workspace 内、限安全后缀。"""
        base = cfg.workspace_dir.resolve()
        p = (base / rel).resolve()
        if (not str(p).startswith(str(base) + "/")) or not p.is_file() \
                or p.suffix.lower() not in companyfile.SAFE_SUFFIX:
            return HTMLResponse("not found", status_code=404)
        # 音频给显式 MIME：mimetypes 对 .m4a 判不稳，octet-stream 会变下载而非播放
        suffix = p.suffix.lower()
        media = companyfile.AUDIO_MIME.get(suffix)
        headers = {"X-Content-Type-Options": "nosniff"}
        if suffix in (".html", ".htm", ".svg"):
            # 这些文件可能是外部来的（附件上传、Notion 附件自动下载），或含被注入的
            # LLM 输出（定制简历），以 text/html 同源渲染 = 同源脚本执行。
            # CSP sandbox：照常渲染给人看，但剥夺脚本与同源身份——预览不受影响。
            headers["Content-Security-Policy"] = "sandbox; default-src 'none'; " \
                                                 "img-src data:; style-src 'unsafe-inline'"
        return FileResponse(p, media_type=media, headers=headers)

    # ---------- API（写操作 = 人在 UI 上的审批动作） ----------

    def _stamp_state(updates: dict) -> None:
        """手动刷新的时间戳走 daemon 内存（单写者）——直接写文件会在 60s 内被
        daemon tick 的整文件快照回滚。无 daemon（测试 / --no-daemon）才落文件。"""
        if daemon is not None:
            daemon.patch_state(updates)
            return
        sp = cfg.workspace_dir / "08-events" / "daemon-state.json"
        try:
            state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        except Exception:
            state = {}
        state.update(updates)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    @app.post("/api/pull")
    def api_pull():
        from joblander.notion import pull_tracker
        rows = pull_tracker(cfg)
        _stamp_state({"last.notion_pull": datetime.now(SGT).isoformat(timespec="seconds")})
        return {"rows": len(rows)}

    @app.post("/api/mcf/scan")
    def api_mcf_scan(days: int = Form(2)):
        from joblander.sourcing import source_mcf
        tid = start_task("mcf", "扫 MyCareersFuture",
                         lambda: {"proposals": len(source_mcf(cfg, _llm("flash"), days=days))})
        return {"ok": True, "task": tid, "label": "扫 MyCareersFuture"}

    @app.post("/api/scan")
    def api_scan(days: int = Form(2)):
        from joblander.gmail_sync import scan

        def run():
            outs = scan(cfg, _llm("flash"), days=days)
            _stamp_state({"last.gmail_scan":
                          datetime.now(SGT).isoformat(timespec="seconds")})
            return {"proposals": len(outs)}
        tid = start_task("scan", "扫描邮箱", run)
        return {"ok": True, "task": tid, "label": "扫描邮箱"}

    @app.post("/api/calendar/refresh")
    def api_calendar_refresh():
        cred = cfg.workspace_dir / ".credentials" / "calendar_token.json"
        if not cred.exists():
            return JSONResponse({"error": "日历未接入（缺 calendar_token）"}, status_code=400)
        from joblander.calendar_sync import upcoming_events
        try:
            events = upcoming_events(cfg, days=7)
        except Exception as e:
            return JSONResponse({"error": f"日历拉取失败:{e}"}, status_code=400)
        now = datetime.now(SGT).isoformat(timespec="seconds")
        _stamp_state({"calendar_cache": {
            "at": now,
            "events": [{k: e.get(k) for k in ("start", "end", "title", "kind")}
                       for e in events]},
            "last.calendar_watch": now})
        return {"events": len(events)}

    @app.post("/api/proposal/apply")
    def api_apply(file: str = Form(...)):
        try:
            return apply_proposal(cfg, file, yes=True)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/proposal/reject")
    def api_reject(file: str = Form(...), reason: str = Form("")):
        return reject_proposal(cfg, file, reason)

    @app.post("/api/proposal/amend_apply")
    async def api_amend_apply(request: Request):
        from joblander.applyops import amend_proposal
        form = dict(await request.form())
        file = form.pop("file")
        try:
            edited = amend_proposal(cfg, file, form)
            result = apply_proposal(cfg, file, yes=True)
            result["edited"] = edited["edited"]
            return result
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/row/archive")
    def api_row_archive(page_id: str = Form(...)):
        from joblander.applyops import archive_row
        try:
            return archive_row(cfg, page_id)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/row/update")
    def api_row_update(page_id: str = Form(...), field: str = Form(...),
                       value: str = Form("")):
        from joblander.applyops import update_row_field
        try:
            return update_row_field(cfg, page_id, field, value)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/daily/notes")
    def api_daily_notes(name: str = Form(...), text: str = Form("")):
        from joblander.daily import save_notes
        try:
            save_notes(cfg, name, text)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/diary/draft")
    def api_diary_draft():
        from joblander.diary import build_diary_draft, today_battle_events
        today = datetime.now(SGT).strftime("%Y-%m-%d")
        if not today_battle_events(cfg, today):     # 快速校验同步做，空转不进托盘
            return JSONResponse({"error": "今天各公司档案还没有战线事件——先去打仗"},
                                status_code=400)
        tid = start_task("diary", "起草今日日记",
                         lambda: build_diary_draft(cfg, _llm("flash")))
        return {"ok": True, "task": tid, "label": "起草今日日记"}

    @app.post("/api/brief")
    def api_brief(company: str = Form(...), note: str = Form(""),
                  round_type: str = Form("")):
        from joblander.prep import ROUND_TEMPLATES, build_brief
        if round_type and round_type not in ROUND_TEMPLATES:
            return JSONResponse({"error": f"未知轮次：{round_type}"}, status_code=400)

        def run():
            out, _ = build_brief(cfg, _llm(), company, round_note=note,
                                 round_type=round_type)
            return {"path": out.name}
        label = f"生成 brief · {company}" + (f" · {round_type}" if round_type else "")
        tid = start_task("brief", label, run)
        return {"ok": True, "task": tid, "label": label}

    @app.post("/api/intake")
    async def api_intake(text: str = Form(""), source: str = Form("paste"),
                         file: UploadFile | None = File(None)):
        from joblander.scout import intake, resolve_intake_text
        text = text.strip()
        jd_rel = ""
        if file is not None and file.filename:      # JD 附件：暂存 + 抽文本并入原文
            import re as _re
            safe = _re.sub(r"[^\w.\-一-鿿（）()]", "_", Path(file.filename).name) or "jd"
            if Path(safe).suffix.lower() not in companyfile.SAFE_SUFFIX:
                return JSONResponse({"error": f"不支持的文件类型：{safe}"}, status_code=400)
            d = cfg.workspace_dir / "12-intake" / "files"
            d.mkdir(parents=True, exist_ok=True)
            dst = d / f"{datetime.now(SGT).strftime('%Y%m%d%H%M%S')}-{safe}"
            dst.write_bytes(await file.read())
            jd_rel = str(dst.relative_to(cfg.workspace_dir))
            extracted = companyfile._file_text(dst)[:20000].strip()
            if extracted:
                text = (text + "\n\n=== JD 附件原文（" + safe + "）===\n"
                        + extracted).strip()
        if not text:
            return JSONResponse({"error": "原文和附件都是空的——总得给一样"}, status_code=400)
        try:
            text, source = resolve_intake_text(cfg, text, source)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        out = intake(cfg, _llm("flash"), text, source_hint=source, jd_file=jd_rel)
        if out is None:
            return JSONResponse({"error": "抽不出公司也抽不出岗位——按噪音忽略（已记账）"},
                                status_code=400)
        return {"proposal": out.name}

    @app.post("/api/scribe")
    async def api_scribe(page_id: str = Form(...), transcript: str = Form(""),
                         file: UploadFile | None = File(None)):
        from joblander.scribe import run_scribe
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        name = row.get("Company") or ""
        attachments: list[str] = []
        text = transcript or ""
        if file is not None and file.filename:
            data = await file.read()
            saved = companyfile.save_upload(cfg, name, file.filename, data, "attachment")
            attachments.append(str(saved.relative_to(cfg.workspace_dir)))
            text = (text + "\n" + companyfile._file_text(saved)).strip()
        if not text:
            return JSONResponse({"error": "转写为空（贴文本或传文件）"}, status_code=400)
        proposal = run_scribe(cfg, _llm(), text, row)
        proposal["attachments"] = attachments
        out_dir = cfg.workspace_dir / "11-shadow"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(SGT).strftime("%Y-%m-%d-%H%M%S")
        out = out_dir / f"{stamp}-{companyfile.slugify(name)}-scribe-shadow.json"
        out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
        _log().append("scribe.shadow_run", "joblander.web",
                      {"company": name, "out": str(out)})
        return {"proposal": out.name}

    # ---------- 公司档案 API ----------

    @app.post("/api/company/meta")
    async def api_company_meta(request: Request):
        form = dict(await request.form())
        row = _row_by_pid(form.pop("page_id", ""))
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        patch = {}
        for k in ("resume_variant", "resume_note", "intake_date"):
            if k in form:
                patch[k] = form[k].strip() or None
        if "highlights" in form:
            patch["highlights"] = [l.strip() for l in form["highlights"].splitlines()
                                   if l.strip()]
        companyfile.save_meta(cfg, row.get("Company") or "", patch)
        return {"ok": True, "fields": sorted(patch.keys())}

    @app.post("/api/company/note")
    def api_company_note(page_id: str = Form(...), kind: str = Form("note"),
                         title: str = Form(""), date: str = Form(""),
                         participants: str = Form(""), content: str = Form("")):
        import re as _re
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        name = row.get("Company") or ""
        people = [p for p in _re.split(r"[,，、;；]", participants) if p.strip()]
        entry = companyfile.timeline_add(
            cfg, name, kind=kind, title=title, date=date or None,
            content_md=content, participants=[p.strip() for p in people],
            author="human", source="manual")
        suggested = None
        if len((content or "").strip()) >= 60:      # 记录不白记：顺手出字段建议（提案制）
            try:
                from joblander.scribe import suggest_fields
                out = suggest_fields(cfg, _llm("flash"), row, content, ref=entry["id"])
                suggested = out.name if out else None
            except Exception:
                suggested = None
        return {"ok": True, "id": entry["id"], "suggested": suggested}

    @app.get("/api/tasks")
    def api_tasks():
        return recent_tasks()

    @app.post("/api/tasks/dismiss")
    def api_tasks_dismiss(id: str = Form(...)):
        t = TASKS.get(id)
        if t and t["status"] != "running":     # 跑着的不许销单——托盘必须如实
            TASKS.pop(id, None)
        return {"ok": True}

    @app.post("/api/resume/react")
    def api_resume_react(page_id: str = Form(...), message: str = Form("")):
        """定制简历唯一入口。聊与出版分离：消息先给教练（事实出入库提案、意见并入
        累积意见集合、答疑引导）；只有用户**显式要求**才出版——消息里明确说「出一版」
        （教练判 generate 意图位），或空消息点 ⚙ 按钮。单轮生成：弹药库 × JD × 累积
        意见集合整份重新出版，不再自动多轮改稿——招聘方视角评审改成按钮手动触发。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        co = row.get("Company") or ""
        message = message.strip()
        chat: dict = {}
        if message:
            from joblander.resume_chat import talk
            try:
                chat = talk(cfg, _llm(), co, message)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            if not chat.get("generate"):
                return {"ok": True, "chat": chat}      # 聊归聊：不烧版本，教练引导确认

        def run_customise():
            from joblander.resume_agent import customise
            out = customise(cfg, _llm(), co, notion_client=_notion())
            return {"v": out["version"]["v"], "sentinel": out["sentinel"]}
        tid = start_task("resume_react", f"定制简历 · {co}", run_customise)
        return {"ok": True, "chat": chat, "task": tid,
                "label": f"定制简历 · {co}"}

    @app.post("/api/resume/reset")
    def api_resume_reset(page_id: str = Form(...)):
        """清空重来：版本与对话归档（不物理删除），教练记忆归零。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        from joblander.resume_agent import reset
        return {"ok": True, **reset(cfg, row.get("Company") or "")}

    @app.post("/api/resume/chat/apply")
    def api_resume_chat_apply(page_id: str = Form(...), plan_id: str = Form(...)):
        """确认入库：执行对话里的归档计划（只追加不删改，⚠️ 段拒收）。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        from joblander.resume_chat import apply_plan
        try:
            return apply_plan(cfg, row.get("Company") or "", plan_id)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/resume/eval")
    def api_resume_eval(page_id: str = Form(...), version: str = Form("")):
        """招聘方视角评当前定制版（无定制版则评母版）：盲评 + 教练分拣，回写版本条目。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        co = row.get("Company") or ""

        def run_eval():
            from evals.resume_eval import run as resume_eval_run
            out = resume_eval_run(cfg, co, version=version)
            v = (out.get("recruiter") or {}).get("verdict") or {}
            return {"interview": v.get("interview"),
                    "needs_user": len((out.get("coach") or {}).get("needs_user") or [])}
        tid = start_task("resume_eval", f"招聘方评估 · {co}", run_eval)
        return {"ok": True, "task": tid}

    @app.post("/api/md/preview")
    def api_md_preview(text: str = Form("")):
        return {"html": md_to_html(text)}

    @app.post("/api/company/entry/detach")
    def api_company_entry_detach(page_id: str = Form(...), entry_id: str = Form(...),
                                 rel: str = Form(...)):
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        try:
            companyfile.detach_attachment(cfg, row.get("Company") or "", entry_id, rel)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/company/entry/edit")
    def api_company_entry_edit(page_id: str = Form(...), entry_id: str = Form(""),
                               date: str = Form(""), title: str = Form(""),
                               kind: str = Form(""), new_date: str = Form(""),
                               new_title: str = Form(""), participants: str = Form(""),
                               summary: str = Form(""), content_md: str = Form(""),
                               review: str = Form(""), review_set: str = Form("")):
        # review_set：空串在可选表单字段上会折叠成缺省，「清空复盘」和「没带字段」
        # 靠这个显式标志区分（统一编辑表单恒带；老调用方不带则复盘不动）
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        name = row.get("Company") or ""
        fields: dict = {"kind": kind, "date": new_date, "title": new_title,
                        "summary": summary, "content_md": content_md,
                        "participants": [p.strip() for p in participants.split("、")
                                         if p.strip()] or
                                        [p.strip() for p in participants.split(",")
                                         if p.strip()]}
        fields = {k: v for k, v in fields.items() if v not in ("", [])}
        try:
            entry = companyfile.edit_entry(cfg, name, entry_id=entry_id,
                                           date=date, title=title, fields=fields)
            # 复盘随编辑态一起保存（统一入口）：变了才写，清空即删
            if review_set and entry.get("id"):
                cur = next((x.get("my_review") or {}
                            for x in companyfile.local_entries(cfg, name)
                            if x.get("id") == entry["id"]), {})
                if review.strip() != (cur.get("text") or "").strip():
                    if review.strip():
                        companyfile.set_review(cfg, name, entry_id=entry["id"],
                                               text=review.strip())
                    else:
                        companyfile.update_entry(cfg, name, entry["id"],
                                                 {"my_review": None})
            return {"ok": True, "id": entry.get("id")}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/company/review")
    def api_company_review(page_id: str = Form(...), entry_id: str = Form(""),
                           date: str = Form(""), title: str = Form(""),
                           text: str = Form(...)):
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        name = row.get("Company") or ""
        entry = companyfile.set_review(cfg, name, entry_id=entry_id, date=date,
                                       title=title, text=text)
        return {"ok": True, "id": entry.get("id")}

    @app.post("/api/company/upload")
    async def api_company_upload(page_id: str = Form(...), kind: str = Form("attachment"),
                                 entry_id: str = Form(""),
                                 file: UploadFile = File(...)):
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        name = row.get("Company") or ""
        data = await file.read()
        saved = companyfile.save_upload(cfg, name, file.filename or "file", data, kind)
        rel = str(saved.relative_to(cfg.workspace_dir))
        if entry_id:
            entries = {e.get("id"): e for e in companyfile.local_entries(cfg, name)}
            if entry_id in entries:
                atts = entries[entry_id].get("attachments") or []
                companyfile.update_entry(cfg, name, entry_id,
                                         {"attachments": atts + [rel]})
        elif kind != "jd":
            companyfile.timeline_add(cfg, name, kind="note",
                                     title=f"附件：{saved.name}", attachments=[rel],
                                     author="human", source="upload")
        return {"ok": True, "file": rel}

    @app.post("/api/offers/save")
    async def api_offers_save(request: Request):
        data = await request.json()
        offers = []
        for o in data.get("offers", []):
            if not (o.get("name") and o.get("base_monthly")):
                continue
            try:
                offers.append({
                    "name": str(o["name"]).strip(),
                    "base_monthly": float(o["base_monthly"]),
                    "currency": (o.get("currency") or "SGD").strip() or "SGD",
                    "bonus_months": float(o.get("bonus_months") or 0),
                    "bonus_pct": float(o.get("bonus_pct") or 0),
                    "equity_face_annual": float(o.get("equity_face_annual") or 0),
                    "equity_tier": (o.get("equity_tier") or "heavy").strip() or "heavy",
                    "bonus_guaranteed": bool(o.get("bonus_guaranteed")),
                    "notes": str(o.get("notes") or "")})
            except (TypeError, ValueError):
                continue
        d = cfg.workspace_dir / "15-offers"
        d.mkdir(parents=True, exist_ok=True)
        (d / "offers.json").write_text(json.dumps(offers, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        _log().append("offers.saved", "human_direct",
                      {"names": [o["name"] for o in offers]})
        return {"ok": True, "n": len(offers)}

    @app.post("/api/sourcing/prefs")
    async def api_sourcing_prefs(request: Request):
        from joblander.sourcing import save_prefs
        form = dict(await request.form())
        patch: dict = {}
        for k in ("intent", "notes", "linkedin_profile"):
            if k in form:
                patch[k] = form[k].strip()
        for k in ("keywords", "locations", "exclude"):
            if k in form:
                patch[k] = [s.strip() for s in form[k].replace("，", ",").split(",")
                            if s.strip()]
        save_prefs(cfg, patch)
        return {"ok": True}

    def _timeline_upsert(co: str, *, title_prefix: str, source: str, **kw):
        return companyfile.timeline_upsert(cfg, co, title_prefix=title_prefix,
                                           source=source, **kw)

    @app.post("/api/company/entry/delete")
    def api_entry_delete(page_id: str = Form(...), entry_id: str = Form(""),
                         date: str = Form(""), title: str = Form("")):
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        try:
            out = companyfile.delete_entry(cfg, row["Company"], entry_id=entry_id,
                                           date=date, title=title)
            return {"ok": True, **out}
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/company/flag")
    def api_company_flag(page_id: str = Form(...), on: str = Form(...)):
        """手动「在你手上」旗标开关——自动待办（提案/到期 follow-up）算不出来
        的球权状态，他自己标；作战室 ⚑ 体系与突出显示据此生效。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        val = str(on).lower() in ("1", "true", "on")
        companyfile.set_my_flag(cfg, row.get("Company") or "", val)
        return {"ok": True, "flag": val}

    @app.post("/api/company/jd_paste")
    def api_company_jd_paste(page_id: str = Form(...), text: str = Form("")):
        """贴入 JD：全文直接落档；纯链接自动抓正文（MCF 走结构化 API）存成
        可在系统内阅读的 markdown，并顺手补空着的 Job URL。"""
        import re as _re
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        t = (text or "").strip()
        if not t:
            return JSONResponse({"error": "内容是空的"}, status_code=400)
        name = row.get("Company") or ""
        now = datetime.now(SGT)
        src_url = t if _re.fullmatch(r"https?://\S+", t) else ""
        if src_url:
            from joblander.scout import resolve_intake_text
            try:
                body, hint = resolve_intake_text(cfg, t, "paste")
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            content = (f"# JD（链接抓取 · {hint}）\n\n- 来源：{src_url}\n"
                       f"- 抓取：{now.strftime('%Y-%m-%d %H:%M')}（岗位页会过期，以原链为准）"
                       f"\n\n---\n\n{body}")
            fname = f"jd-链接抓取-{now.strftime('%Y%m%d-%H%M%S')}.md"
            # 同链接重贴 = 刷新快照：旧快照移入回收站，不叠加喂给评估
            jd_dir = companyfile.company_dir(cfg, name) / "jd"
            for old in (companyfile.list_files(cfg, name, "jd") if jd_dir.exists() else []):
                if not old["name"].endswith(".md"):
                    continue
                try:
                    txt = (jd_dir / old["name"]).read_text(encoding="utf-8",
                                                           errors="replace")
                except Exception:
                    continue
                if f"- 来源：{src_url}\n" in txt:
                    companyfile.remove_jd_file(cfg, name, old["name"])
        else:
            content = (f"# JD（人工贴入）\n\n- 录入：{now.strftime('%Y-%m-%d %H:%M')}"
                       f"\n\n---\n\n{t}")
            fname = f"jd-贴入-{now.strftime('%Y%m%d-%H%M')}.md"
        out = companyfile.save_upload(cfg, name, fname, content.encode("utf-8"), kind="jd")
        url_filled = False
        if src_url and not (row.get("Job URL") or "").strip():
            from joblander.applyops import update_row_field
            try:
                update_row_field(cfg, page_id, "Job URL", src_url)
                url_filled = True
            except Exception:
                pass
        return {"ok": True, "file": out.name, "chars": len(content),
                "url_filled": url_filled}

    @app.post("/api/company/jd_delete")
    def api_company_jd_delete(page_id: str = Form(...), name: str = Form(...)):
        """删 JD 文件：移入 jd/.trash/ + 记墓碑——自动挖掘（Notion 附件/targets
        播种/链接抓取）不得拉回；同名重新手动上传即解除。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        try:
            return {"ok": True,
                    **companyfile.remove_jd_file(cfg, row.get("Company") or "", name)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.get("/api/company/jd_raw")
    def api_company_jd_raw(page_id: str, name: str):
        """编辑弹窗取原文：仅 .md/.txt（PDF 不可编辑，只能删了重传）。"""
        row = _row_by_pid(page_id)
        if row is None or "/" in name or name.startswith("."):
            return JSONResponse({"error": "行不存在或非法文件名"}, status_code=400)
        p = companyfile.company_dir(cfg, row.get("Company") or "") / "jd" / name
        if not p.is_file() or p.suffix.lower() not in companyfile.EDITABLE_SUFFIX:
            return JSONResponse({"error": "文件不存在或不可编辑"}, status_code=400)
        return {"ok": True, "name": name,
                "text": p.read_text(encoding="utf-8", errors="replace")}

    @app.post("/api/company/jd_edit")
    def api_company_jd_edit(page_id: str = Form(...), name: str = Form(...),
                            text: str = Form("")):
        """改写 JD 文本文件：旧版自动存 jd/.trash/ 再覆盖（可恢复）。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        try:
            return {"ok": True, **companyfile.edit_jd_file(
                cfg, row.get("Company") or "", name, text)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.get("/company/{page_id}/jd/{name}", response_class=HTMLResponse)
    def jd_view(request: Request, page_id: str, name: str):
        """JD 文件的系统内阅读页：文本/markdown 渲染阅读，其余类型转 /files 原样打开。"""
        row = _row_by_pid(page_id)
        if row is None or ".." in name or "/" in name:
            return HTMLResponse("not found", status_code=404)
        p = companyfile.company_dir(cfg, row.get("Company") or "") / "jd" / name
        if not p.is_file():
            return HTMLResponse("not found", status_code=404)
        if p.suffix.lower() not in (".md", ".txt"):
            return RedirectResponse(f"/files/{p.relative_to(cfg.workspace_dir)}")
        head = (f'<div class="note" style="margin-bottom:12px">JD 文件 · {p.name} · '
                f'<a href="/company/{page_id}#cards">← 回 {row["Company"]}</a></div>')
        return tpl.TemplateResponse(request, "doc.html", ctx(
            "pipe", title=f"{p.name} · {row['Company']}",
            html=head + md_to_html(p.read_text(encoding="utf-8", errors="replace"))))

    @app.post("/api/company/research")
    def api_company_research(page_id: str = Form(...), urls: str = Form(""),
                             notes: str = Form("")):
        """W2/W3 尽调（单路径）。给了 URL/材料 = 喂入种子打底，缺口照常补搜；
        什么都不给 = 零输入 ReAct 多轮检索。综合简介带编号来源，落时间线。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        url_list = [u.strip() for u in urls.splitlines() if u.strip().startswith("http")]
        materials = [{"label": "贴入材料", "text": notes.strip()}] if notes.strip() else []
        co = row["Company"]

        def run_deep():
            from joblander.researcher import diligence, format_deep_summary
            jd = companyfile.jd_text(cfg, co)
            d = diligence(cfg, _llm(), co, context="；".join(filter(None, [
                f"目标岗位：{row.get('Position')}" if row.get("Position") else "",
                f"阶段：{row.get('Status')}" if row.get("Status") else "",
                f"战况：{row.get('Highlight')}" if row.get("Highlight") else ""])),
                jd_text=jd, seed_urls=url_list, seed_materials=materials)
            seeded = d.get("seeded") or {}
            fed = len(seeded.get("urls", [])) + len(seeded.get("materials", []))
            _timeline_upsert(co, title_prefix=("尽调", "Deep Research"),
                source="researcher", title="尽调报告：公司综合简介",
                summary=f"{1 + len(d.get('trail', []))} 轮检索 · "
                        f"{len(d.get('sources', []))} 个来源 · "
                        f"{len(d.get('facts', []))} 条事实"
                        + (f"（喂入 {fed} 份）" if fed else "")
                        + ("（含 JD）" if jd else ""),
                content_md=format_deep_summary(d))
            return {"sources": len(d.get("sources", [])),
                    "rounds": 1 + len(d.get("trail", [])),
                    "facts": len(d.get("facts", [])), "seeds": fed}
        tid = start_task("research", f"尽调 · {co}", run_deep)
        return {"ok": True, "task": tid}

    @app.post("/api/company/referral")
    def api_company_referral(page_id: str = Form(...)):
        """W14 内推匹配（存量公司手动补跑；新入库自动跑）。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        co = row["Company"]

        def run():
            from joblander.referral import format_referral_md, suggest_referral
            ref = suggest_referral(cfg, _llm("flash"), co)
            if ref.get("error"):
                raise RuntimeError(ref["error"])
            _timeline_upsert(co, title_prefix="内推匹配", source="referral",
                title="内推匹配（W14）",
                summary=f"{len(ref.get('matches') or [])} 位候选",
                content_md=format_referral_md(ref))
            return {"matches": len(ref.get("matches") or [])}

        tid = start_task("referral", f"内推匹配 · {co}", run)
        return {"ok": True, "task": tid}

    @app.post("/api/coordinator/slots")
    def api_coordinator_slots(page_id: str = Form(...), text: str = Form(...)):
        """W6 排期参谋：贴入邀约 → 时段规则对照 + 回复草稿，产物落公司档案。"""
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        if len(text.strip()) < 10:
            return JSONResponse({"error": "邀约文本太短"}, status_code=400)
        co = row["Company"]

        def run():
            from joblander.coordinator import format_slot_report, suggest_slots
            out = suggest_slots(cfg, _llm(), text, company=co)
            report = format_slot_report(out)
            companyfile.timeline_add(
                cfg, co, kind="note", title="排期参谋：候选时段对照与回复草稿",
                content_md=report, summary=(out["best"] or {}).get("start", "无可约时段"),
                author="ai", source="coordinator")
            _log().append("coordinator.slots_suggested", "joblander.web",
                          {"company": co, "slots": len(out["slots"]),
                           "ok": bool(out["best"]), "calendar_ok": out["calendar_ok"]})
            return {"company": co, "best": (out["best"] or {}).get("start")}

        tid = start_task("slots", f"排期参谋 · {co}", run)
        return {"ok": True, "task": tid}

    @app.post("/api/company/assess")
    def api_company_assess(page_id: str = Form(...)):
        row = _row_by_pid(page_id)
        if row is None:
            return JSONResponse({"error": "行不存在"}, status_code=400)
        try:
            result = companyfile.assess(cfg, _llm(), row)
            return {"ok": True, "jd_match": (result.get("jd_match") or {}).get("score"),
                    "salary_match": (result.get("salary_match") or {}).get("score")}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    return app
