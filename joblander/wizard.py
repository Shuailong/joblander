"""网页设置向导（云端版的 W0）：不碰 config.yaml、不手建文件，三步把系统喂到能用。

1. 旧简历 → 弹药库初稿 + profile.json（LLM 只做搬运与拆分，不许补写简历里没有的事实）
2. 目标总包 + 红线词 → policy / sentinel（写进 config）
3. 求职偏好 → 交给「新机会」页现成的编辑器

「完成」= 弹药库 + 身份 + 报价锚点三样齐：简历定制、brief、Offer 对比的硬依赖。
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any

from joblander.config import update_config

SKIP_MARK = ("08-events", "setup-skipped")
# 生成走后台任务、按钮可连点：不加锁的话几个任务同时过「已有弹药库」检查，
# 各花一次钱、后完成的覆盖先完成的（云端实测：20 秒内跑了 3 次）
_BOOTSTRAP_LOCK = threading.Lock()

# Analyst 硬依赖 fx；向导给一张默认表（→ SGD），用户日后可在 config 里改
DEFAULT_FX = {"SGD": 1.0, "USD": 1.34, "EUR": 1.45, "GBP": 1.70, "RMB": 0.186,
              "HKD": 0.172, "JPY": 0.0089, "AUD": 0.88}
DEFAULT_DISCOUNT = {"light": 1.0, "medium": 0.5, "heavy": 0.0}

BANK_SYSTEM = """你把一份旧简历拆成「战绩弹药库」初稿。弹药库是之后所有定制简历、面试 brief 的唯一事实来源，所以：
- 只搬运简历里明确写了的事实；不补写、不美化、不推测数字。简历没写的就不出现。
- 数字、公司名、职位名、时间逐字照抄。
- 按公司/项目/教育分段（sections），每段若干条战绩（items）：headline 是一句话概括，detail 是原文里的支撑细节（可多行）。
- 另抽出身份信息：姓名 + 联系方式（邮箱/电话/LinkedIn/GitHub/个人网站等，有链接的给 href，邮箱用 mailto:）。
只输出 JSON：
{"profile": {"name": "...", "contact": [{"text": "...", "href": "..."}]},
 "sections": [{"title": "公司 · 职位 · 起止时间", "items": [{"headline": "...", "detail": "..."}]}]}"""

RED_LINE_SECTION = """## 【⚠️ 素材使用注意】

- 只用本库写明的事实；库里没有的经历、数字一律不得出现在对外材料里
- 数字逐字使用，不取整、不换算口径
- 本库由旧简历自动拆出——请逐段核对、补充细节后再大量使用"""


def _ws(cfg):
    return cfg.workspace_dir


def bank_path(cfg):
    return _ws(cfg) / "03-materials" / "achievement-bank.md"


def profile_path(cfg):
    return _ws(cfg) / "03-materials" / "profile.json"


def status(cfg) -> dict[str, Any]:
    bank = bank_path(cfg)
    has_bank = bank.exists() and "### " in bank.read_text(encoding="utf-8")
    try:
        prof = json.loads(profile_path(cfg).read_text(encoding="utf-8"))
        has_profile = bool(prof.get("name"))
    except Exception:
        has_profile = False
    pol = cfg.raw.get("policy") or {}
    has_policy = bool(pol.get("quote_tc_sgd")) and bool(pol.get("fx"))
    has_prefs = (_ws(cfg) / "02-targets" / "sourcing-prefs.yaml").exists()
    st = {"bank": has_bank, "profile": has_profile, "policy": has_policy,
          "sentinel": bool(cfg.sentinel_rules), "prefs": has_prefs,
          "skipped": _ws(cfg).joinpath(*SKIP_MARK).exists()}
    st["done"] = has_bank and has_profile and has_policy
    return st


def needs_setup(cfg) -> bool:
    st = status(cfg)
    return not st["done"] and not st["skipped"]


def skip(cfg) -> None:
    p = _ws(cfg).joinpath(*SKIP_MARK)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("1", encoding="utf-8")


def render_bank(sections: list[dict]) -> str:
    """LLM 的结构化拆分 → 弹药库 markdown。条目编号 A1、A2… 全库连续——
    教练归档、brief 引用与 brief_eval 的幻觉编号检查都靠它。"""
    out = ["# 战绩弹药库", "",
           "> 由旧简历自动拆出的初稿。逐段核对、补上简历里装不下的细节——这里写得越实，定制简历越好。"]
    n = 0
    for s in sections:
        title = str(s.get("title") or "").strip()
        items = [i for i in (s.get("items") or []) if str(i.get("headline") or "").strip()]
        if not title or not items:
            continue
        out += ["", f"## {title}"]
        for it in items:
            n += 1
            out += ["", f"### A{n}. {str(it['headline']).strip()}"]
            detail = str(it.get("detail") or "").strip()
            if detail:
                out.append(detail)
    if not n:
        raise ValueError("没能从简历里拆出任何条目——换一份文字版简历（不是扫描图片）再试")
    return "\n".join(out) + "\n\n" + RED_LINE_SECTION + "\n"


def bootstrap_from_resume(cfg, llm, resume_text: str) -> dict[str, Any]:
    """旧简历文本 → 弹药库 + profile.json。已有弹药库不覆盖（那是用户核对过的心血）。"""
    text = (resume_text or "").strip()
    if len(text) < 200:
        raise ValueError("简历文字太少——可能是扫描版 PDF，换一份能选中文字的版本")
    if not _BOOTSTRAP_LOCK.acquire(blocking=False):
        raise ValueError("弹药库正在生成中——稍等一分钟，不用重复点")
    try:
        return _bootstrap(cfg, llm, text)
    finally:
        _BOOTSTRAP_LOCK.release()


def bank_has_content(cfg) -> bool:
    return bank_path(cfg).exists() and bool(bank_path(cfg).read_text(encoding="utf-8").strip())


def generating() -> bool:
    return _BOOTSTRAP_LOCK.locked()


def _bootstrap(cfg, llm, text: str) -> dict[str, Any]:
    from joblander.company import atomic_write_text
    from joblander.eventlog import EventLog
    from joblander.scribe import _strip_fences

    if bank_has_content(cfg):
        raise ValueError("弹药库已经有内容了——去弹药库页直接编辑，向导不覆盖")
    try:
        raw = json.loads(_strip_fences(llm.generate(
            f"【旧简历原文】\n{text[:30000]}\n\n按系统提示输出 JSON。",
            system=BANK_SYSTEM, json_mode=True)))
    except (json.JSONDecodeError, ValueError):
        raise ValueError("拆分结果不是合法 JSON——重试一次") from None
    bank_md = render_bank(raw.get("sections") or [])
    atomic_write_text(bank_path(cfg), bank_md)

    wrote_profile = False
    prof = raw.get("profile") or {}
    if prof.get("name") and not profile_path(cfg).exists():
        contact = [{"text": str(c.get("text") or "").strip(), "href": str(c.get("href") or "").strip()}
                   for c in (prof.get("contact") or []) if str(c.get("text") or "").strip()]
        atomic_write_text(profile_path(cfg), json.dumps(
            {"name": str(prof["name"]).strip(), "contact": contact}, ensure_ascii=False, indent=1))
        wrote_profile = True
    n_items = len(re.findall(r"^### A\d+\.", bank_md, flags=re.M))
    EventLog(_ws(cfg) / "08-events" / "event-log.jsonl").append(
        "setup.bank_bootstrapped", "agent:wizard", {"items": n_items, "profile": wrote_profile})
    return {"items": n_items, "profile": wrote_profile}


def save_basics(cfg, target_tc: float, currency: str, redlines: list[str]) -> None:
    """目标总包 → policy.quote_tc_sgd（引擎内部统一按 SGD 比较）；红线词 → 一条 pattern 规则。"""
    from joblander.eventlog import EventLog

    currency = (currency or "SGD").upper()
    fx = {**DEFAULT_FX, **((cfg.raw.get("policy") or {}).get("fx") or {})}
    if currency not in fx:
        raise ValueError(f"不支持的币种：{currency}（可选：{'、'.join(fx)}）")
    if not target_tc or target_tc <= 0:
        raise ValueError("目标年度总包要填一个正数")
    pol = cfg.raw.get("policy") or {}
    patch: dict[str, Any] = {"policy": {
        "quote_tc_sgd": round(target_tc * fx[currency]),
        "quote_input": {"amount": target_tc, "currency": currency},
        "fx": fx,
        "equity_discount_factors": pol.get("equity_discount_factors") or DEFAULT_DISCOUNT,
    }}
    words = [w.strip() for w in redlines if w.strip()]
    others = [r for r in cfg.sentinel_rules if r.get("id") != "wizard-redlines"]
    if words:
        others.append({"id": "wizard-redlines", "type": "pattern", "action": "block",
                       "patterns": [re.escape(w) for w in words],
                       "why": "设置向导里填的红线词", "guidance": "换成可以对外说的表述"})
    patch["sentinel"] = {"rules": others}
    update_config(cfg, patch)
    EventLog(_ws(cfg) / "08-events" / "event-log.jsonl").append(
        "setup.basics_saved", "human_direct", {"currency": currency, "redlines": len(words)})


# ---------- 功能开关 ----------
# 练兵场偏计算机岗，默认关；关着时代码执行端点直接拒（不只是藏入口）。
# LinkedIn 抓取走免登录的公开职位接口（条款灰区），默认开、可关。
FEATURES = {"drill": False, "linkedin": True}


def features(cfg) -> dict[str, bool]:
    raw = cfg.raw.get("features") or {}
    return {k: bool(raw.get(k, default)) for k, default in FEATURES.items()}


def set_feature(cfg, name: str, on: bool) -> None:
    if name not in FEATURES:
        raise ValueError(f"未知功能：{name}")
    update_config(cfg, {"features": {name: on}})
