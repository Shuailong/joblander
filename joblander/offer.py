"""W13 Offer 拆解与对比 — Analyst 纯函数之上的对比矩阵 + 谈判 brief 骨架。"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from joblander.analyst import offer_snapshot

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖


def compare_offers(policy: dict[str, Any], offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """offers: [{"name": ..., "base_monthly": ..., "currency", "bonus_months"|"bonus_pct",
                 "equity_face_annual", "equity_tier", "bonus_guaranteed": bool, "notes": str}]
    返回按折价 TC 排序的快照列表（含结构确定性标记）。"""
    out = []
    for o in offers:
        snap = offer_snapshot(
            policy,
            base_monthly=o["base_monthly"],
            currency=o.get("currency", "SGD"),
            bonus_months=o.get("bonus_months", 0.0),
            bonus_pct=o.get("bonus_pct", 0.0),
            equity_face_annual=o.get("equity_face_annual", 0.0),
            equity_tier=o.get("equity_tier", "heavy"),
        )
        snap["name"] = o["name"]
        snap["bonus_guaranteed"] = bool(o.get("bonus_guaranteed", False))
        snap["notes"] = o.get("notes", "")
        out.append(snap)
    return sorted(out, key=lambda s: s["tc_discounted_sgd"], reverse=True)


def offer_matrix_md(policy: dict[str, Any], offers: list[dict[str, Any]]) -> str:
    rows = compare_offers(policy, offers)
    md = ["# Offer 对比矩阵（W13）",
          f"> 生成 {datetime.now(SGT).isoformat(timespec='minutes')} ｜ 原则：报价按面值、比较按折价；结构确定性 > 数字",
          "",
          "| Offer | 现金/年 | 期权面值 | TC 面值 | **TC 折价** | vs 锚点 | bonus 保底 | 备注 |",
          "|---|---|---|---|---|---|---|---|"]
    for s in rows:
        md.append(f"| {s['name']} | {s['cash_sgd']:,} | {s['equity_face_sgd']:,} "
                  f"| {s['tc_face_sgd']:,} | **{s['tc_discounted_sgd']:,}** "
                  f"| {s['gap_vs_anchor_pct']:+.1f}% | {'✅' if s['bonus_guaranteed'] else '—'} "
                  f"| {s['notes']} |")
    md += ["", "谈判提醒（Playbook/Sentinel）：",
           f"- 锚点口径：约 {policy.get('quote_tc_sgd', 0):,} 带 base+bonus+equity 拆解；绝不透露底线与参考换算线",
           "- 重折价期权的公司 → 谈判重心压现金",
           "- 多 offer 尽量对齐时间窗制造竞争"]
    return "\n".join(md) + "\n"


def build_offer_matrix(cfg, offers: list[dict[str, Any]]) -> Path:
    text = offer_matrix_md(cfg.policy, offers)
    out_dir = cfg.workspace_dir / "15-offers"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now(SGT).strftime('%Y-%m-%d')}-offer-matrix.md"
    out.write_text(text, encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "offer.matrix_built", "joblander.offer", {"offers": [o["name"] for o in offers]})
    return out
