"""W4 薪酬调研 — deep research，用户触发（Researcher 证据端 + Analyst 统计端合作）。

数据源诚实声明（v0）：主源 = MyCareersFuture 结构化薪资（新加坡市场硬数据，
逐岗带链接可回查）；可选补充 = 用户给的公开 URL 抓取 + 人工贴入材料。
levels.fyi / Glassdoor 等登录态站点抓不到——复制内容走贴入。

分工纪律：统计层零 LLM（P25/中位/P75 纯代码可测）；LLM 只把数字写成人话。
个人锚点对照只输出相对百分比——报告不含任何私有绝对数字，可安全分享。
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SGT = timezone(timedelta(hours=8))

REPORT_SYSTEM = """你是求职作战系统的薪酬调研分析师。输入：候选人画像摘要、目标方向的市场岗位清单
（含月薪区间，来自 MyCareersFuture 实时数据）、分组统计、可选补充材料。
写一篇 markdown 调研报告（中文，专名保留原文），结构：

## 市场概览
（2-3 段：这批方向当前的供给面貌、薪资水位、值得注意的结构性信号）

## 分方向 band
（每个关键词方向一小节：区间分布怎么读、哪些公司/岗位定价高、和统计表相互印证）

## 与候选人画像的匹配
（哪些岗位簇最值得投、哪些方向溢价与画像强项重合；引用具体岗位时给出 [标题](链接)）

## 信号与风险
（range 虚标、低报价陷阱、数据缺口——哪些结论证据不足要人工核实）

纪律：每个具体断言尽量指向输入里的岗位或材料；数据没有的不编造；
不要复述统计表本身（表会附在报告里），写表读不出来的东西。"""


def collect_market(keywords: list[str], limit_per_kw: int = 30) -> list[dict[str, Any]]:
    """MCF 搜索 → 带月薪区间的岗位行（无薪资/非月薪的丢弃）。失败的关键词跳过不炸。"""
    from joblander.sourcing import mcf_search
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kw in keywords:
        try:
            jobs = mcf_search(kw, limit=limit_per_kw)
        except Exception:
            continue
        for j in jobs:
            uuid = j.get("uuid") or ""
            sal = j.get("salary") or {}
            if uuid in seen or not sal.get("minimum") or not sal.get("maximum"):
                continue
            if ((sal.get("type") or {}).get("salaryType") or "Monthly") != "Monthly":
                continue
            seen.add(uuid)
            lo, hi = float(sal["minimum"]), float(sal["maximum"])
            rows.append({
                "kw": kw,
                "title": (j.get("title") or "").strip(),
                "company": ((j.get("postedCompany") or {}).get("name") or "").strip(),
                "min": lo, "max": hi, "mid": (lo + hi) / 2,
                "url": f"https://www.mycareersfuture.gov.sg/job/{uuid}",
            })
    return rows


def _quantiles(mids: list[float]) -> dict[str, int]:
    if not mids:
        return {}
    qs = statistics.quantiles(mids, n=4) if len(mids) >= 4 else [min(mids), statistics.median(mids), max(mids)]
    return {"n": len(mids), "p25": round(qs[0]), "median": round(statistics.median(mids)),
            "p75": round(qs[-1]), "lo": round(min(mids)), "hi": round(max(mids))}


def salary_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """统计层（零 LLM）：整体 + 按关键词的月薪中值分布。"""
    out: dict[str, Any] = {"all": _quantiles([r["mid"] for r in rows]), "by_kw": {}}
    for kw in sorted({r["kw"] for r in rows}):
        out["by_kw"][kw] = _quantiles([r["mid"] for r in rows if r["kw"] == kw])
    return out


def _stats_table(stats: dict[str, Any]) -> list[str]:
    lines = ["| 方向 | 样本 | P25 | 中位 | P75 | 区间 |",
             "|---|---|---|---|---|---|"]
    def fmt(name: str, q: dict) -> str:
        return (f"| {name} | {q['n']} | {q['p25']:,} | **{q['median']:,}** | "
                f"{q['p75']:,} | {q['lo']:,}–{q['hi']:,} |")
    if stats.get("all"):
        lines.append(fmt("全部", stats["all"]))
    for kw, q in (stats.get("by_kw") or {}).items():
        lines.append(fmt(kw, q))
    lines.append("")
    lines.append("（单位：SGD/月，取每岗区间中值；来源 MCF 实时数据）")
    return lines


def _anchor_note(cfg, stats: dict[str, Any]) -> list[str]:
    """锚点对照（纯代码）：只输出相对百分比，绝对值不上屏（系统惯例）。"""
    med = (stats.get("all") or {}).get("median")
    floor = (cfg.policy or {}).get("base_floor_monthly")
    if not med or not floor:
        return []
    pct = (med / floor - 1) * 100
    verdict = "高于" if pct >= 0 else "低于"
    return ["", "## 对照个人底线（相对值）",
            f"- 市场中位月薪{verdict}你的月 base 底线 **{abs(pct):.0f}%**"
            "（底线绝对值不上屏；MCF 数字是月 base，与总包口径不可直接比）"]


def build_comp_report(cfg, llm, keywords: list[str] | None = None,
                      extra_urls: list[str] | None = None, notes: str = "") -> Path:
    """W4 主流程：MCF 采集 → 统计 → LLM 叙事 → 带日期报告落盘。"""
    if not keywords:
        from joblander.sourcing import load_prefs
        keywords = (load_prefs(cfg).get("keywords") or [])[:6]
    if not keywords:
        raise ValueError("没有调研关键词——「新机会」页的侦察偏好里填 keywords，或调用时直接给")

    market = collect_market(keywords)
    stats = salary_stats(market)

    extras: list[str] = []
    for u in extra_urls or []:
        try:
            from joblander.researcher import fetch_url
            extras.append(f"=== {u} ===\n{fetch_url(u)[:8000]}")
        except Exception as e:
            extras.append(f"=== {u} ===\n（抓取失败：{e}）")
    if notes.strip():
        extras.append(f"=== 人工贴入 ===\n{notes.strip()[:8000]}")

    from joblander.sourcing import _profile_digest
    profile = (_profile_digest(cfg) or "")[:4000]

    job_lines = [f"- [{r['kw']}] {r['title']} · {r['company']} · "
                 f"{r['min']:,.0f}–{r['max']:,.0f}/月 · {r['url']}"
                 for r in sorted(market, key=lambda x: -x["mid"])[:80]]
    narrative = ""
    if market or extras:
        narrative = llm.generate(
            "候选人画像摘要：\n" + (profile or "（空）") + "\n\n"
            "统计（SGD/月，区间中值）：\n" + json.dumps(stats, ensure_ascii=False) + "\n\n"
            "市场岗位清单：\n" + ("\n".join(job_lines) or "（MCF 无有效样本）") + "\n\n"
            "补充材料：\n" + ("\n\n".join(extras) or "（无）"),
            system=REPORT_SYSTEM)

    now = datetime.now(SGT)
    md: list[str] = [
        f"# 薪酬调研 · {now:%Y-%m-%d}",
        f"> joblander W4 ｜ 数据抓取：{now:%Y-%m-%d %H:%M} ｜ "
        f"关键词：{'、'.join(keywords)} ｜ 样本：MCF {len(market)} 个带薪资岗位"
        + (f" + {len(extras)} 份补充材料" if extras else ""),
        "",
        "## Band 统计（统计层，零 LLM）", "",
        *_stats_table(stats),
        *_anchor_note(cfg, stats),
        "",
        narrative or "（无叙事：市场与补充材料均为空）",
        "",
        "## 方法与来源",
        "- 主源：MyCareersFuture 实时搜索（逐岗链接见清单，月薪为雇主自报区间）",
        "- 统计口径：每岗取区间中值；P25/中位/P75 按样本计算",
        "- 时效：岗位数据即抓即用，超过两周建议重跑",
        "",
        "<details><summary>样本清单（按薪资降序，前 80）</summary>", "",
        *(job_lines or ["（无）"]), "", "</details>",
    ]
    out_dir = cfg.workspace_dir / "15-comp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"comp-{now:%Y-%m-%d-%H%M}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")

    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "comp.report_generated", "joblander.compensation",
        {"keywords": keywords, "samples": len(market), "out": str(out)})
    return out
