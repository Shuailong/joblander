"""W14 人脉/内推 — referral-map 匹配（v0：文本检索 + LLM 选人；触达草稿他发）。"""

from __future__ import annotations

import json
from pathlib import Path

REFERRAL_SYSTEM = """你是求职作战系统的内推参谋。输入：目标公司 + 人脉地图原文（LinkedIn 联系人盘点）。
输出严格 JSON（中文）：
{
  "matches": [{"name": "...", "why": "为什么此人合适（关系强度/组织位置）", "channel": "linkedin|wechat|whatsapp|unknown"}],
  "second_degree": ["可能的二度路径"],
  "blind_spot": "若无人脉，一句话说明并给替代打法",
  "outreach_draft": "触达草稿（遵守：他主动发起→给硬数字；一段话，中文或英文按对象）"
}
纪律：只从输入的人脉地图取人名，不编造；草稿永远由用户本人发送。"""


def format_referral_md(result: dict) -> str:
    """suggest_referral 结果 → 落档案的 markdown（触达草稿围栏，他来发）。"""
    lines: list[str] = []
    for m in result.get("matches") or []:
        lines.append(f"- **{m.get('name', '?')}**（{m.get('channel', 'unknown')}）"
                     f"——{m.get('why', '')}")
    if not lines:
        lines.append(f"- 无直接人脉。{result.get('blind_spot', '')}")
    for s in result.get("second_degree") or []:
        lines.append(f"- 二度路径：{s}")
    if result.get("outreach_draft"):
        lines += ["", "**触达草稿（你来发）**", "", "```",
                  result["outreach_draft"].strip(), "```"]
    return "\n".join(lines)


def suggest_referral(cfg, llm, company: str) -> dict:
    from joblander.scribe import _strip_fences

    map_path = cfg.workspace_dir / "04-pipeline" / "referral-map.md"
    if not map_path.exists():
        return {"error": f"人脉地图不存在：{map_path}"}
    raw_map = map_path.read_text(encoding="utf-8", errors="replace")
    raw = llm.generate(f"目标公司：{company}\n\n人脉地图：\n{raw_map[:40000]}",
                       system=REFERRAL_SYSTEM, json_mode=True)
    result = json.loads(_strip_fences(raw))
    result["company"] = company

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "referral.suggested", "joblander.referral",
        {"company": company, "matches": len(result.get("matches", []))})
    return result
