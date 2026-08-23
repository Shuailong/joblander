"""能力画像（W17）— 市场要求 vs 当前能力的双层雷达 + 备战方向。

数据管道（全部从已有数据挖，不拍脑袋）：
- 市场侧：目标公司 JD 语料（公司档案 jd/ + 高分线索 JD 摘录）→ 归纳能力轴 + 需求强度
- 自身侧：面试/通话复盘（时间线 + 我的复盘）+ 初筛 req_gaps（现成的差距清单）
纪律：能力轴从 JD 归纳而非预设；self 分必须有复盘证据支撑，宁低勿虚高；prep 必须可执行。
产出 03-materials/capability.json（私有 workspace），打法页渲染雷达 + 维度卡。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SGT = timezone(timedelta(hours=8))

CAPABILITY_SYSTEM = """你是求职能力画像分析师。输入五部分：①目标公司 JD 语料 ②本人履历与战绩库 ③面试/通话复盘 ④初筛发现的硬性差距清单 ⑤用户手工校准（若有）。
输出严格 JSON（中文）：
{"dimensions": [
   {"name": "能力轴名（≤8 字，从 JD 语料归纳，6-8 个轴）",
    "market": 1-5,   ← 该能力在 JD 语料中的需求强度/出现频度
    "self": 1-5,
    "subs": [{"name": "二级维度（≤10 字，2-4 个，用来精确定位强弱）",
              "self": 1-5, "note": "一句证据或短板，引复盘优先"}],
    "evidence": ["支撑评分的具体证据——优先引复盘原话，其次引履历战绩，必须非空，最多 2 条"],
    "gap": "一句话差距（无差距则空串）",
    "prep": ["准备动作，最多 2 条"],
    "suggested_self": 仅当该维度有用户校准且新复盘证据明确支持不同分时给出,
    "suggest_why": "同上，一句话引证据"}],
 "strengths": ["最强的 2 个轴，各一句话（轴名+为什么）"],
 "focus": ["最该补的 2 个方向，各一句话（轴名+第一步动作）"],
 "summary": "三句话：最强的牌 / 最要命的缺口 / 下一步方向"}
评分纪律（反虚高——2026-08-08 用户纠偏后的铁律）：
- **「做过」≠「精通」**：履历只能证明经历不能证明水平；self ≥4 必须有面试实战验证
  （复盘显示该能力被考察且打住了），否则封顶 3
- **只按实际动作计入，禁止领域外推**：为某领域项目做了工程交付 ≠ 懂该领域——
  例：给合规项目新增几个语言的 NLU 服务并上线，只计入多语言工程交付，
  **不构成**合规/监管能力；同理「用过多智能体框架」是相关经验，不是专家
- **复盘证据 > 履历自述，负面证据 > 正面自述**：复盘暴露的短板（如某场面试
  系统设计的抽象建模、问题到数据结构的映射不精确）必须落到对应维度与二级维度并压分
- **用户手工校准是权威**：有校准的维度 self 必须等于校准分；若新复盘证据明确支持
  不同分，只写 suggested_self + suggest_why 供参考，不得直接改
- 轴从 JD 语料归纳，不预设清单；差距清单里反复出现的技能应成轴
- **轴名延续性**：【用户手工校准】里出现过的轴名，只要语料仍支持就沿用原名——
  轴名抖动会甩掉用户的校准
- **prep 禁止空话**（『参加培训』『参与项目积累经验』『提升能力』一律不许出现）——
  必须是本周就能开工、有产出物的动作；能从已有战绩改造的优先于从零学"""


TERMINAL = {"Terminated", "Not Apply", "Rejected", "Withdrawn"}


def _jd_corpus(cfg, rows: list[dict], notion_client=None,
               scope: dict | None = None) -> tuple[str, list[dict]]:
    """市场要求侧的 JD 语料按策略选公司（他拍板：画像要有重点）：
    high（默认）= High 优先级机会；custom = 他在参谋部页点名的公司清单。
    每家走三级挖掘（Notion 附件 > 本地 > 链接），逐家注明来源。"""
    from joblander.company import mine_jd
    scope = scope or {}
    picked = set((scope.get("companies") or [])
                 if scope.get("mode") == "custom" else ())
    parts: list[str] = []
    companies: list[dict] = []
    for r in rows:
        if picked:
            if (r.get("Company") or "").strip() not in picked:
                continue
        elif r.get("Priority") != "High" or r.get("Status") in TERMINAL:
            continue
        t, origin = mine_jd(cfg, r, notion_client=notion_client)
        companies.append({"company": r.get("Company"), "origin": origin})
        if t:
            parts.append(f"=== {r.get('Company')}（{r.get('Position') or ''}）"
                         f"｜JD 来源：{origin} ===\n{t[:2500]}")
    return "\n\n".join(parts)[:16000], companies


def _evidence_corpus(cfg, limit: int = 40) -> list[dict]:
    from joblander.company import BATTLE_KINDS, local_entries
    base = cfg.workspace_dir / "18-companies"
    out: list[dict] = []
    if base.exists():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            for e in local_entries(cfg, d.name):
                if e.get("kind") in BATTLE_KINDS:
                    out.append({"company": d.name, "date": e.get("date"),
                                "title": e.get("title") or "",
                                "record": (e.get("content_md") or "")[:800],
                                "my_review": (e.get("my_review") or {}).get("text", "")})
    return sorted(out, key=lambda x: x.get("date") or "")[-limit:]


def _gap_signals(cfg) -> list[str]:
    """初筛与匹配评估攒下的差距清单——市场已经告诉过你缺什么。"""
    from joblander.company import load_meta
    sigs: list[str] = []
    try:
        from joblander.applyops import list_pending
        for p in list_pending(cfg):
            for g in ((p.get("fit") or {}).get("req_gaps") or []):
                sigs.append(f"{(p.get('lead') or {}).get('company') or p.get('company')}："
                            f"{g.get('req')}（{g.get('verdict')}）")
    except Exception:
        pass
    base = cfg.workspace_dir / "18-companies"
    if base.exists():
        for d in sorted(base.iterdir()):
            if d.is_dir():
                a = load_meta(cfg, d.name).get("assessment") or {}
                for g in (a.get("jd_match") or {}).get("gaps") or []:
                    sigs.append(f"{d.name}：{g}")
    return sigs[:40]


def capability_path(cfg) -> Path:
    return cfg.workspace_dir / "03-materials" / "capability.json"


def load_capability(cfg) -> dict[str, Any]:
    p = capability_path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """人工校准落到维度上：校准分覆盖 LLM 分（LLM 原分保留在 self_llm 供对照）。"""
    ov = data.get("overrides") or {}
    matched: set = set()

    def _bind(d, key, o):
        if d.get("self") != o.get("self"):
            d["self_llm"] = d.get("self")
        d["self"] = o.get("self")
        d["override_note"] = o.get("note", "")
        matched.add(key)

    dims = data.get("dimensions") or []
    for d in dims:
        o = ov.get(d.get("name"))
        if o:
            _bind(d, d.get("name"), o)
    for key, o in ov.items():                     # 轴名微调兜底：包含式匹配（系统设计与架构 ↔ 系统设计）
        if key in matched:
            continue
        hit = next((d for d in dims if "override_note" not in d
                    and (key in d.get("name", "") or d.get("name", "") in key)), None)
        if hit is not None:
            _bind(hit, key, o)
    data["unmatched_overrides"] = sorted(k for k in ov if k not in matched)
    return data


def set_scope(cfg, mode: str, companies: list[str] | None = None) -> dict[str, Any]:
    """配置市场侧 JD 策略：high = High 优先级；custom = 点名公司清单。
    跟 overrides 一样存在 capability.json 顶层，跨重估存续；下次重估生效。"""
    if mode not in ("high", "custom"):
        raise ValueError(f"未知 JD 策略：{mode}")
    companies = [c.strip() for c in (companies or []) if c.strip()]
    if mode == "custom" and not companies:
        raise ValueError("自定义策略至少选一家公司")
    data = load_capability(cfg)
    data["jd_scope"] = {"mode": mode, "companies": companies}
    capability_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    capability_path(cfg).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "capability.scope_set", "human_direct",
        {"mode": mode, "companies": companies})
    return data


def set_override(cfg, name: str, self_score: int, note: str = "") -> dict[str, Any]:
    """用户手调某维度的当前能力分——权威值，重估不得推翻（只能附建议）。"""
    data = load_capability(cfg)
    ov = data.setdefault("overrides", {})
    ov[name] = {"self": int(self_score), "note": note,
                "at": datetime.now(SGT).strftime("%Y-%m-%d")}
    apply_overrides(data)
    capability_path(cfg).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "capability.overridden", "human_direct",
        {"dimension": name, "self": int(self_score), "note": note[:120]})
    return data


def build_capability(cfg, llm, notion_client=None) -> dict[str, Any]:
    from joblander.prep import _load_projection
    from joblander.scribe import _strip_fences

    prev = load_capability(cfg)
    prev_overrides = prev.get("overrides") or {}
    scope = prev.get("jd_scope") or {"mode": "high", "companies": []}
    rows = _load_projection(cfg)
    jd, jd_companies = _jd_corpus(cfg, rows, notion_client=notion_client, scope=scope)
    jd_n = sum(1 for c in jd_companies if c["origin"] != "无")
    scope_label = ("High 优先级机会" if scope["mode"] == "high"
                   else f"自定义清单：{'、'.join(scope['companies'])}")
    evidence = _evidence_corpus(cfg)
    gaps = _gap_signals(cfg)
    from joblander.sourcing import _profile_digest
    profile = _profile_digest(cfg, limit=12000)   # 主源=弹药库（与初筛同一对照面）
    prompt = (f"【目标公司 JD 语料（{scope_label}，{jd_n} 家）】\n"
              f"{jd or '（该范围暂无 JD 文件——按差距清单与复盘归纳，并在 summary 提醒补 JD）'}\n\n"
              f"【本人履历与战绩库】\n{profile or '（未配置）'}\n\n"
              f"【复盘证据（{len(evidence)} 份）】\n"
              + json.dumps(evidence, ensure_ascii=False)[:18000]
              + f"\n\n【初筛差距清单】\n" + ("\n".join(f"- {s}" for s in gaps) or "（无）")
              + "\n\n【用户手工校准（权威——输出 self 必须遵从）】\n"
              + ("\n".join(f"- {k}：self={v['self']}（{v.get('note','')}）"
                           for k, v in prev_overrides.items()) or "（无）"))
    raw = llm.generate(prompt, system=CAPABILITY_SYSTEM, json_mode=True)
    data = json.loads(_strip_fences(raw))
    data["built_at"] = datetime.now(SGT).strftime("%Y-%m-%d %H:%M")
    data["sources"] = {"jd_high_n": jd_n, "jd_chars": len(jd),
                       "jd_companies": jd_companies, "jd_mode": scope["mode"],
                       "evidence_n": len(evidence), "gap_signals_n": len(gaps)}
    data["overrides"] = prev_overrides          # 手调与 JD 策略跨重估存续
    data["jd_scope"] = scope
    apply_overrides(data)

    p = capability_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    from joblander.eventlog import EventLog
    EventLog(cfg.workspace_dir / "08-events" / "event-log.jsonl").append(
        "capability.built", "joblander.capability",
        {"dims": len(data.get("dimensions") or []), **data["sources"]})
    return data
