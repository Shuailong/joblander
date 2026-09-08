"""User Agent —— 以使用者人设评估 Web 产品（可用 → 能用 → 好用）。

走真实旅程（live server 或 TestClient），每一步把页面可见文本交给 LLM 评审员，
按固定量规打分并列具体问题；汇总报告落 workspace/16-audits/。
用法：python -m evals.user_agent [--base http://127.0.0.1:8899]
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

PERSONA = """你是评审员，扮演这个产品的真实用户：一名被裁后高强度求职的资深工程师。
画像：日均 1–3 场面试/通话；注意力是最稀缺资源（设计目标：日常喂养 <15 分钟/天）；
关心的只有四件事——今天该干嘛、面前有没有弹药、面后 30 秒能不能交差、系统有没有替我守住口径。
他见过好软件（Notion/Linear 级别），对糙的 UI 没有耐心。"""

RUBRIC = """对给出的页面（纯文本渲染，无样式信息——只评信息架构与文案，不评视觉）按三档打分：
- 可用（1-5）：这一步的任务能不能完成？信息在不在？
- 能用（1-5）：动作路径清不清楚？点几下能完成？有没有死胡同/歧义？
- 好用（1-5）：信息密度与优先级对不对？文案是否说人话？有没有替用户省心的细节？
输出严格 JSON：{"scores":{"usable":n,"workable":n,"delightful":n},
"issues":[{"sev":"P0|P1|P2","what":"具体问题","fix":"一句话修法"}],"praise":["值得保留的点"]}
纪律：issues 必须指向页面里真实存在/缺失的内容，不许泛泛而谈；每页最多 5 条。"""

JOURNEY = [
    ("/", "早上打开系统：30 秒内我要知道今天干什么、有什么等着我批（各自在哪批要指得清）"),
    ("/sourcing", "晨起决策新机会：待入池按匹配度排好、低分折叠、能批量清；"
                  "偏好我能自己改；哪些渠道自动哪些要我动手，一眼分清"),
    ("/pipeline", "扫一眼战线（看板+表格）：谁最要紧、各阶段几家、拖卡片换阶段"),
    ("/company/{first_pid}", "一家公司的主战场：三卡、待批提案（带上下文批）、备战弹药、"
                             "时间线全史（AI 与我写的分得清）；面试完在这页贴转写、写我的复盘"),
    ("/system", "偶尔看一眼：系统在替我干什么、守卫开着没、Notion 并行状态"),
]


def fetch_text(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=30) as r:
        html = r.read().decode()
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", html)
    return re.sub(r"\n{2,}", "\n", re.sub(r"[ \t]+", " ", text)).strip()[:12000]


def run(base: str) -> str:
    from joblander.config import load_config
    from joblander.llm import from_config
    from joblander.scribe import _strip_fences

    cfg = load_config()
    llm = from_config(cfg, "eval")   # 评测裁判永远最强档

    proj = json.loads((cfg.workspace_dir / "09-projections" / "tracker.json")
                      .read_text(encoding="utf-8"))
    first_pid = next(r["notion_page_id"] for r in proj["rows"]
                     if r.get("Status") == "Interview Scheduled")

    now = datetime.now(SGT)
    lines = [f"# UX 评估（User Agent）· {now.strftime('%Y-%m-%d %H:%M')}",
             f"> 人设：高强度求职者 ｜ 量规：可用/能用/好用 各 1–5 ｜ 对象：{base}", ""]
    totals = {"usable": 0, "workable": 0, "delightful": 0}
    all_p0p1: list[str] = []

    for path, goal in JOURNEY:
        real = path.replace("{first_pid}", first_pid)
        text = fetch_text(base, real)
        raw = llm.generate(
            f"用户此刻的目标：{goal}\n\n页面路径：{real}\n页面文本：\n{text}",
            system=PERSONA + "\n\n" + RUBRIC, json_mode=True)
        r = json.loads(_strip_fences(raw))
        s = r.get("scores", {})
        for k in totals:
            totals[k] += int(s.get(k, 0))
        lines.append(f"## `{real}` — {goal}")
        lines.append(f"可用 **{s.get('usable')}** ｜ 能用 **{s.get('workable')}** ｜ 好用 **{s.get('delightful')}**")
        for i in r.get("issues", []):
            lines.append(f"- [{i.get('sev')}] {i.get('what')} → {i.get('fix')}")
            if i.get("sev") in ("P0", "P1"):
                all_p0p1.append(f"{real}: {i.get('what')} → {i.get('fix')}")
        for p in r.get("praise", [])[:2]:
            lines.append(f"- ✅ {p}")
        lines.append("")

    n = len(JOURNEY)
    lines.insert(2, f"**总分：可用 {totals['usable']}/{n*5} ｜ 能用 {totals['workable']}/{n*5} "
                    f"｜ 好用 {totals['delightful']}/{n*5} ｜ P0/P1 问题 {len(all_p0p1)} 条**")
    report = "\n".join(lines) + "\n"

    out_dir = cfg.workspace_dir / "16-audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.strftime('%Y-%m-%d-%H%M')}-ux-eval.md"
    out.write_text(report, encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "ux.evaluated", "evals.user_agent",
        {"totals": totals, "p0p1": len(all_p0p1), "out": str(out)})
    print(report)
    return str(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    run(ap.parse_args().base)
