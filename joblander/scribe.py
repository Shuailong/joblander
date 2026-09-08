"""Scribe 书记 — W8/W9：转写 → 结构化提案（录入 + 复盘 + Playbook 战况）。

输出永远是 ChangeProposal 语义：不直接写任何 SoT（P6/ADR-2）。
产出先过 Sentinel（internal 受众：拦截降级为标注），findings 附在提案上。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from joblander.sentinel import Audience, Sentinel

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖

SCRIBE_SYSTEM = """你是求职作战系统的书记官（Scribe）。输入一场求职通话/面试的转写或纪要，以及该公司在 tracker 的当前行、跨面试问题模式清单（Playbook）。

输出严格 JSON（不要 markdown 代码围栏），**全部用中文**（band 数字、专有名词、引语保留原文），结构：
{
  "field_diffs": {
    "Status": "仅当转写明确表明阶段变化才给出。保守规则：『会安排/等排期』不算 Interview Scheduled，必须有确定时间才算；拒绝/终止要有明确表述",
    "Highlight": "一句短语（表格扫读用）。风格示例：『band 顶仍低于锚点；合规经验是唯一差异资产』『口头承诺不低于当前总包；负责人下周初审』——信息密度优先",
    "Next Steps": "一句话动作（谁、做什么、何时）",
    "Follow-up Reminder": "YYYY-MM-DD 或 null"
  },
  "body_entry": "以「### YYYY-MM-DD 事件/人名」开头的 markdown 条目。先【录入】后【复盘】。【录入】必须穷尽以下类别（转写里有就必录，数字逐字）：①薪酬每一项——base、bonus 结构（保底/target/月数）、equity/LTI 性质与流动性、补贴，含币种；②流程——轮次、每轮形式、时间线、下一步与时限；③地点与办公政策（onsite/hybrid/remote、主招地）；④对方的承诺、要求与风险信号；⑤团队/组织情报。宁多勿漏——录入是档案不是摘要。【复盘】做归因：命中/失误/行动项，重点找『该打没打的牌』，不是流水账",
  "playbook_updates": [{"id": "P1..P8", "outcome": "hit|miss|partial|untested", "note": "一句话"}],
  "confidence_notes": ["转写不清或推断处，标 ⚠️待确认，不许硬猜"]
}

复盘纪律：对照输入的 Playbook 清单**逐条检查**——该模式在本场是否被触发？触发了打得如何（hit/miss/partial）？没触发写 untested 或不写。严禁把无关内容贴到模式上。
约定：Highlight 一句短语；数字日期逐字；field_diffs 只含确有变化的字段；录入（事实）与复盘（判断）分开。"""


def _playbook_summary(cfg) -> str:
    """8 条模式的 id + pattern + status，注入 Scribe prompt 供逐条对照。"""
    try:
        from joblander.prep import _load_playbook
        entries = _load_playbook(cfg)
    except Exception:
        entries = []
    if not entries:
        return "（无 Playbook）"
    return "\n".join(f"- {p['id']}（{p.get('status','?')}）：{p.get('pattern','')}" for p in entries)


def _strip_fences(raw: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL)
    return (m.group(1) if m else raw).strip()


def run_scribe(cfg, llm, transcript_text: str, row: dict[str, Any],
               today: str | None = None) -> dict[str, Any]:
    today = today or datetime.now(SGT).strftime("%Y-%m-%d")
    row_slim = {k: row.get(k) for k in
                ("Company", "Position", "Status", "Priority", "Next Steps",
                 "Highlight", "Follow-up Reminder", "Contact Person")}
    playbook_lines = _playbook_summary(cfg)
    prompt = (
        f"今天：{today}\n"
        f"Status 可选值：Added/Dream/In Consideration/To Apply/Screening Called/Applied/"
        f"Interview Scheduled/Interview Completed/Terminated/Not Apply/Offer Received/Rejected/Withdrawn\n"
        f"tracker 当前行：{json.dumps(row_slim, ensure_ascii=False)}\n\n"
        f"Playbook 模式清单（复盘逐条对照）：\n{playbook_lines}\n\n"
        f"转写/纪要全文：\n{transcript_text[:80000]}"
    )
    raw = llm.generate(prompt, system=SCRIBE_SYSTEM, json_mode=True)
    data = json.loads(_strip_fences(raw))

    sentinel = Sentinel.from_config(cfg)
    checked_text = (data.get("body_entry") or "") + "\n" + json.dumps(
        data.get("field_diffs") or {}, ensure_ascii=False)
    verdict = sentinel.check(checked_text, audience=Audience.INTERNAL)

    judgment: list[dict] = []
    if cfg.raw.get("sentinel", {}).get("judgment_checks"):
        try:                                    # 判断层入流水线：失败不阻塞（冷落安全）
            from joblander.judge import judge
            judgment = [f for f in judge(cfg, llm, checked_text,
                                         context_note=f"{row.get('Company')} 面后复盘记录")
                        if f.get("verdict") == "attention"]
        except Exception as e:
            judgment = [{"check": "judgment-layer", "verdict": "attention",
                         "note": f"判断层运行失败：{e}"}]

    return {
        "company": row.get("Company"),
        "notion_page_id": row.get("notion_page_id"),
        "field_diffs": data.get("field_diffs") or {},
        "body_entry": data.get("body_entry") or "",
        "playbook_updates": data.get("playbook_updates") or [],
        "confidence_notes": data.get("confidence_notes") or [],
        "sentinel": verdict.explain(),
        "judgment": judgment,
        "approved": None,   # ChangeProposal 语义：等人批
    }


SUGGEST_SYSTEM = """从一条人工战报记录中提取 tracker 字段更新建议。只在记录内容明确支持时才给字段，宁缺勿滥。
输出严格 JSON：{"field_diffs": {"Status": "仅确定的阶段变化（『会安排』不算 Interview Scheduled）",
 "Next Steps": "一句话动作", "Follow-up Reminder": "YYYY-MM-DD", "Highlight": "一句短语"}}
只输出确有变化的键；没有可建议的输出 {"field_diffs": {}}。"""


def suggest_fields(cfg, llm, row: dict[str, Any], note_text: str,
                   ref: str = "") -> Path | None:
    """人工新增事件 → 字段修改建议提案（2026-08-08 他的设计：记录不该白记，
    字段跟着记录走——但仍是提案，批了才写）。无建议返回 None。"""
    today = datetime.now(SGT).strftime("%Y-%m-%d")
    row_slim = {k: row.get(k) for k in ("Company", "Position", "Status",
                                        "Next Steps", "Highlight", "Follow-up Reminder")}
    raw = llm.generate(
        f"今天：{today}\nStatus 可选值：Added/Dream/In Consideration/To Apply/"
        f"Screening Called/Applied/Interview Scheduled/Interview Completed/Terminated/"
        f"Not Apply/Offer Received/Rejected/Withdrawn\n"
        f"tracker 当前行：{json.dumps(row_slim, ensure_ascii=False)}\n\n"
        f"记录全文：\n{note_text[:6000]}",
        system=SUGGEST_SYSTEM, json_mode=True)
    diffs = (json.loads(_strip_fences(raw)).get("field_diffs") or {})
    diffs = {k: v for k, v in diffs.items()
             if v and k in ("Status", "Next Steps", "Follow-up Reminder", "Highlight")
             and row.get(k) != v}
    if not diffs:
        return None
    proposal = {
        "origin": "note.suggest", "company": row.get("Company"),
        "notion_page_id": row.get("notion_page_id"),
        "field_diffs": diffs, "body_entry": "", "playbook_updates": [],
        "sentinel": "PASS", "ref": ref, "approved": None,
    }
    out_dir = cfg.workspace_dir / "12-intake"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = (row.get("Company") or "x").split("（")[0].strip().replace(" ", "-").replace("/", "-")[:30]
    out = out_dir / f"{datetime.now(SGT).strftime('%Y-%m-%d-%H%M%S')}-{slug}-suggest.json"
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "note.fields_suggested", "joblander.scribe",
        {"company": row.get("Company"), "fields": sorted(diffs), "out": str(out)})
    return out


def load_transcript(path: str | Path) -> str:
    """转写加载：.md/.txt 直读；.pdf 走 pypdf 文本抽取（豆包导出 PDF 为文本型）。"""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8")


def shadow_run(cfg, llm, transcript_path: str | Path, company_row: dict[str, Any]) -> Path:
    """W8 正式链路（函数名与 11-shadow 目录为历史命名）：转写 → 提案落待批队列，
    批准后 apply_proposal 落 tracker 字段 + 档案时间线 + Playbook——不批不写。"""
    transcript = load_transcript(transcript_path)
    proposal = run_scribe(cfg, llm, transcript, company_row)

    out_dir = cfg.workspace_dir / "11-shadow"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(SGT).strftime("%Y-%m-%d-%H%M")
    slug = (company_row.get("Company") or "unknown").split("（")[0].strip().replace(" ", "-").replace("/", "-")
    out = out_dir / f"{stamp}-{slug}-scribe-shadow.json"
    out.write_text(json.dumps(proposal, ensure_ascii=False, indent=1), encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "scribe.shadow_run", "joblander.scribe",
        {"company": company_row.get("Company"), "transcript": str(transcript_path), "out": str(out)})
    return out
