"""常驻调度器（F1 的运行时形态）——把「工具箱」变成「系统」。

设计取舍：不引入 celery/APScheduler，单线程 tick 循环（60s）+ 状态文件去重。
每个 job 独立 try/except（一个失败不拖垮循环），失败落 job.failed 事件（DLQ 语义），
次日晨报可见（失败不允许静默，DESIGN §8.3）。
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SGT = timezone(timedelta(hours=8))


class Daemon:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state_path = cfg.workspace_dir / "08-events" / "daemon-state.json"
        self.state: dict[str, Any] = self._load_state()
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self.jobs: list[tuple[str, Callable[[], Any]]] = [
            ("transcript_watch", self.job_transcript_watch),   # 每 tick
            ("calendar_watch", self.job_calendar_watch),       # 30min
            ("notion_diff_pull", self.job_notion_diff_pull),   # 15min
            ("gmail_scan", self.job_gmail_scan),               # 30min
            ("nightly_sourcing", self.job_nightly_sourcing),   # 每日 02:30 夜扫
            ("morning_report", self.job_morning_report),       # 每日 08:15
            ("evening_diary", self.job_evening_diary),         # 每日 21:30
            ("weekly_report", self.job_weekly),                # 周日 20:00
        ]

    # ---------- 基础设施 ----------

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_state(self):
        with self._state_lock:
            snapshot = json.dumps(self.state, ensure_ascii=False, indent=1)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(snapshot, encoding="utf-8")

    def patch_state(self, updates: dict[str, Any]) -> None:
        """web 端手动刷新写 state 的唯一入口——daemon 是 state 的单写者。
        （此前 web 直接写文件，60s 后被 daemon tick 的内存快照整文件回滚——
        「上次刷新时间刚更新又变旧」的根因。）"""
        with self._state_lock:
            self.state.update(updates)
        self._save_state()

    def _log(self):
        from joblander.eventlog import EventLog
        return EventLog(self.cfg.workspace_dir / "08-events" / "event-log.jsonl")

    def _llm(self, tier: str = "pro"):
        from joblander.llm import from_config
        return from_config(self.cfg, tier)

    def _due_interval(self, key: str, minutes: int) -> bool:
        last = self.state.get(f"last.{key}", "")
        now = datetime.now(SGT)
        if last and (now - datetime.fromisoformat(last)).total_seconds() < minutes * 60:
            return False
        self.state[f"last.{key}"] = now.isoformat(timespec="seconds")
        return True

    def _due_daily(self, key: str, hh: int, mm: int, weekday: int | None = None) -> bool:
        now = datetime.now(SGT)
        if weekday is not None and now.weekday() != weekday:
            return False
        if (now.hour, now.minute) < (hh, mm):
            return False
        today = now.strftime("%Y-%m-%d")
        if self.state.get(f"done.{key}") == today:
            return False
        self.state[f"done.{key}"] = today
        return True

    # ---------- jobs ----------

    def job_transcript_watch(self):
        """转写收件箱新文件 → 自动 W8 影子 → 通知。

        目录名：文档（DESIGN §614 / MIGRATION）与 onboard 脚手架都用 06-transcripts，
        但这里长期硬编码成 06-communites（作者早期的拼写），于是新用户把转写扔进
        文档写的目录，看守的却是另一个永远不存在的目录——W8 自动链路对除作者以外
        的所有人从未启动过。两个都认：先看规范目录，回落到历史目录（作者的存量在那）。
        """
        from joblander.prep import _load_projection, find_row
        from joblander.scribe import shadow_run

        ws = self.cfg.workspace_dir
        inbox = next((d for d in (ws / "06-transcripts", ws / "06-communites")
                      if d.is_dir()), None)
        if inbox is None:
            return
        # 首启只标存量、不处理——但「空收件箱」也得算已初始化。原来用 `if not seen`
        # 判断，空列表同样为假，于是此后掉进来的第一份转写会被标已见后直接跳过。
        if "transcripts_seen" not in self.state:
            self.state["transcripts_seen"] = [f.name for f in inbox.iterdir() if f.is_file()]
            return
        seen: list[str] = self.state["transcripts_seen"]
        rows = _load_projection(self.cfg)
        names = sorted({(r.get("Company") or "") for r in rows}, key=len, reverse=True)
        for f in sorted(inbox.iterdir()):
            if not f.is_file() or f.name in seen or f.suffix.lower() not in (".md", ".txt", ".pdf"):
                continue
            seen.append(f.name)
            row = None
            base = f.stem.casefold()
            for n in names:
                short = n.split("（")[0].strip().casefold()
                if short and short in base:
                    row = find_row(rows, n)
                    break
            if row is None:
                self._log().append("transcript.unmatched", "daemon", {"file": f.name})
                continue
            out = shadow_run(self.cfg, self._llm(), f, row)
            from joblander.notify import notify
            notify("面后提案就绪", f"{row.get('Company')} 的录入+复盘等你批（档案页顶部）",
                   f"http://127.0.0.1:8899/company/{row.get('notion_page_id')}#pending")
            self._log().append("daemon.auto_scribe", "daemon",
                               {"file": f.name, "company": row.get("Company"),
                                "out": str(out)})

    def job_calendar_watch(self):
        """T-24h / T-2h 自动弹药（每场每档一次）。"""
        if not self._due_interval("calendar_watch", 30):
            return
        cred = self.cfg.workspace_dir / ".credentials" / "calendar_token.json"
        if not cred.exists():
            return
        from joblander.calendar_sync import upcoming_events
        from joblander.notify import notify
        from joblander.prep import _load_projection, build_brief, find_row, guess_round

        rows = _load_projection(self.cfg)
        now = datetime.now(SGT)
        done: list[str] = self.state.setdefault("briefed", [])
        events = upcoming_events(self.cfg, days=7)
        # 近 7 天场次缓存 → 「今天」页展示今日日历、周报「下周三件事」找冲刺目标
        self.state["calendar_cache"] = {
            "at": now.isoformat(timespec="seconds"),
            "events": [{k: e.get(k) for k in ("start", "end", "title", "kind")}
                       for e in events]}
        for ev in events:
            if ev.get("kind") != "interview" or "T" not in str(ev.get("start")):
                continue
            start = datetime.fromisoformat(ev["start"])
            hours = (start - now).total_seconds() / 3600
            stage = "T24" if 2 < hours <= 24 else ("T2" if 0 < hours <= 2 else None)
            if not stage:
                continue
            key = f"{ev['start']}::{stage}"
            if key in done:
                continue
            row = None
            title = ev["title"].casefold()
            for r in rows:
                short = (r.get("Company") or "").split("（")[0].strip().casefold()
                if short and short in title:
                    row = r
                    break
            done.append(key)
            if row is None:
                continue
            note = f"自动生成（{stage}）：{ev['title']} @ {ev['start']}"
            out, _ = build_brief(self.cfg, self._llm(), row["Company"], round_note=note,
                                 round_type=guess_round(ev["title"]))
            notify(f"弹药就绪（{stage}）", f"{row['Company']} · {ev['start'][11:16]} 开打",
                   "http://127.0.0.1:8899/briefs/" + out.name)
            # 这条事件原先误缩进在下面的 `if newgaps:` 里，引用的 row/stage/out 只在本循环
            # 绑定：有排期缺口但本 tick 没有 T-24h/T-2h 场次时（常态）直接 UnboundLocalError，
            # 被 tick() 记成 job.failed 污染 /system 的失败计数，而事件本身从未落过。
            self._log().append("daemon.auto_brief", "daemon",
                               {"company": row["Company"], "stage": stage, "out": str(out)})

        # tracker ↔ 日历同步：错位 → 提案（写日历永远等他在 UI 上确认详情）
        from joblander.coordinator import schedule_gaps
        gaps = schedule_gaps(rows, self.state["calendar_cache"]["events"],
                             now.strftime("%Y-%m-%d"))
        newgaps = 0
        wk = now.strftime("%Y-W%W")
        out_dir = self.cfg.workspace_dir / "12-intake"
        for g in gaps:
            key = f"gap.{g['type']}.{(g.get('page_id') or '')[:12]}.{wk}"
            if self.state.get(key):
                continue                          # 每缺口每周最多提一次，不催办
            self.state[key] = now.isoformat(timespec="seconds")
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = (g.get("company") or "x").split("（")[0].strip() \
                .replace(" ", "-").replace("/", "-")[:30]
            stamp = now.strftime("%Y-%m-%d-%H%M%S")
            if g["type"] == "missing_calendar":
                prop = {"kind": "calendar.event", "company": g["company"],
                        "notion_page_id": g.get("page_id"),
                        "title": f"面试：{g['company']}",
                        "date": g.get("date") or "", "time": "",
                        "duration_min": 60,
                        "note": "tracker 已排面但日历没这场——补上时间，确认即建",
                        "approved": None}
                fn = f"{stamp}-{slug}-calgap.json"
            else:
                prop = {"origin": "calendar.sync", "company": g["company"],
                        "notion_page_id": g.get("page_id"),
                        "field_diffs": {"Status": "Interview Scheduled",
                                        "Follow-up Reminder": str(g.get("start", ""))[:10]},
                        "body_entry": f"### {now.strftime('%Y-%m-%d')} 日历同步：{g.get('event_title')}\n\n"
                                      f"- 日历已有场次 {g.get('start')}，tracker 未跟上——批准即对齐",
                        "playbook_updates": [], "sentinel": "PASS",
                        "approved": None}
                fn = f"{stamp}-{slug}-calsync.json"
            (out_dir / fn).write_text(json.dumps(prop, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
            newgaps += 1
        if newgaps:
            notify("排期缺口", f"{newgaps} 处 tracker↔日历错位待处理",
                   "http://127.0.0.1:8899/")

    def job_notion_diff_pull(self):
        """F2：定时 pull + diff → notion.edited 事件回流。没配 Notion 直接跳过——
        它是可选集成，此前无条件 pull 让纯本地用户每 15 分钟收获一条 job.failed。"""
        from joblander.notion import notion_configured
        if not notion_configured(self.cfg):
            return
        if not self._due_interval("notion_pull", 15):
            return
        from joblander.notion import pull_tracker_with_diff
        pull_tracker_with_diff(self.cfg)

    def job_gmail_scan(self):
        if not self._due_interval("gmail_scan", 30):
            return
        cred = self.cfg.workspace_dir / ".credentials" / "gmail_token.json"
        if not cred.exists():
            return
        from joblander.gmail_sync import scan
        from joblander.notify import notify
        outs = scan(self.cfg, self._llm("flash"), days=1)
        if outs:
            notify("新线索待入池", f"{len(outs)} 条等你决策（新机会）",
                   "http://127.0.0.1:8899/sourcing")

    def job_nightly_sourcing(self):
        """夜扫（W1 主动侦察）：他睡觉时按偏好抓 MCF 新岗 → fit 评分 → 待入池；晨起决策。
        Gmail 侧的 job alert 邮件由 30min 循环持续覆盖，夜扫不重复拉。"""
        if not self._due_daily("sourcing", 2, 30):
            return
        from joblander.notify import notify
        from joblander.sourcing import source_mcf
        outs = source_mcf(self.cfg, self._llm("flash"), days=2)
        if outs:
            notify("夜扫收获", f"{len(outs)} 条新机会已评分待决策（新机会）",
                   "http://127.0.0.1:8899/sourcing")

    def job_morning_report(self):
        if not self._due_daily("morning", 8, 15):
            return
        from joblander.daily import build_daily
        from joblander.notify import notify
        from joblander.notion import NotionClient
        # 没配 Notion 就出纯本地晨报（CLI 的 daily 一直是这么做的，daemon 这条漏了改）——
        # 否则纯本地用户每天 08:15 只收到一条 KeyError，永远等不到晨报。
        from joblander.notion import notion_configured
        client = (NotionClient(self.cfg.raw["notion"]["token"])
                  if notion_configured(self.cfg) else None)
        out, text = build_daily(self.cfg, notion_client=client)
        first = next((l for l in text.splitlines() if l.startswith("#")), "晨报")
        notify("晨报出炉", first.lstrip("# "), "http://127.0.0.1:8899/")

    def job_evening_diary(self):
        if not self._due_daily("diary", 21, 30):
            return
        from joblander.diary import build_diary_draft
        from joblander.notify import notify
        out = build_diary_draft(self.cfg, self._llm("flash"))
        if out is not None:
            notify("日记草稿就绪", "改两句定稿进参谋部日报（指挥中心）",
                   "http://127.0.0.1:8899/#diary")

    def job_weekly(self):
        if not self._due_daily("weekly", 20, 0, weekday=6):
            return
        from joblander.notion import NotionClient
        from joblander.notify import notify
        from joblander.weekly import build_weekly
        build_weekly(self.cfg, llm=self._llm())
        try:                                      # 周度顺手重估能力画像（复盘攒了一周新证据）
            from joblander.capability import build_capability
            from joblander.notion import notion_configured
            build_capability(self.cfg, self._llm(),
                             notion_client=(NotionClient(self.cfg.raw["notion"]["token"])
                                            if notion_configured(self.cfg) else None))
        except Exception:
            pass
        notify("周报出炉", "战果 · 下周的仗 · 复盘提炼 · 能力画像已重估（参谋部）",
               "http://127.0.0.1:8899/playbook")

    # ---------- 主循环 ----------

    def tick(self):
        for name, fn in self.jobs:
            try:
                fn()
            except Exception as e:                      # DLQ 语义：失败入账不静默
                self._log().append("job.failed", "daemon",
                                   {"job": name, "error": str(e)[:300],
                                    "trace": traceback.format_exc()[-500:]})
        self._save_state()

    def run_forever(self, interval: int = 60):
        self._log().append("daemon.started", "daemon", {"jobs": [n for n, _ in self.jobs]})
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(interval)

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, daemon=True, name="joblander-daemon")
        t.start()
        return t

    def stop(self):
        self._stop.set()
