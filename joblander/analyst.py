"""Analyst 纯函数 — 策略即代码（DESIGN §7.3）。

换算/折价/对比全部是纯函数；LLM 只负责把计算结果写成人话（不在本文件）。
所有阈值来自私有 config 的 policy 段，本文件零硬编码。
policy v2：一切数字为参考值非闸门——函数返回信息与解释，不返回「否决」。
"""

from __future__ import annotations

from typing import Any

DEFAULT_DISCOUNT = {"light": 1.0, "medium": 0.5, "heavy": 0.0}


def to_sgd(amount: float, currency: str, fx: dict[str, float]) -> float:
    cur = currency.upper()
    if cur == "SGD":
        return float(amount)
    if cur not in fx:
        raise KeyError(f"fx 表缺少币种 {cur}（决策前先补汇率假设）")
    return float(amount) * fx[cur]


def annual_cash(base_monthly: float, bonus_months: float = 0.0, bonus_pct: float = 0.0) -> float:
    """年现金 = 12 个月 base + 月数制 bonus + 百分比制 bonus。"""
    base_annual = base_monthly * 12
    return base_annual + base_monthly * bonus_months + base_annual * bonus_pct


def equity_annual_value(face_value_annual: float, tier: str,
                        factors: dict[str, float] | None = None) -> float:
    """股权年化：报价按面值，比较按折价（STRATEGY 折价三档）。"""
    f = factors or DEFAULT_DISCOUNT
    if tier not in f:
        raise KeyError(f"未知折价档 {tier}（可选：{sorted(f)}）")
    return face_value_annual * f[tier]


def offer_snapshot(policy: dict[str, Any], *,
                   base_monthly: float,
                   currency: str = "SGD",
                   bonus_months: float = 0.0,
                   bonus_pct: float = 0.0,
                   equity_face_annual: float = 0.0,
                   equity_tier: str = "heavy") -> dict[str, Any]:
    """一个 offer/band 的标准化快照：现金、面值 TC、折价 TC、对锚点位置。"""
    fx = policy["fx"]
    factors = policy.get("equity_discount_factors", DEFAULT_DISCOUNT)
    anchor = policy["quote_tc_sgd"]

    cash_sgd = to_sgd(annual_cash(base_monthly, bonus_months, bonus_pct), currency, fx)
    equity_face_sgd = to_sgd(equity_face_annual, currency, fx)
    tc_face = cash_sgd + equity_face_sgd
    tc_discounted = cash_sgd + equity_annual_value(equity_face_sgd, equity_tier, factors)

    gap_pct = tc_face / anchor - 1
    if tc_face >= anchor:
        position = "at_or_above_anchor"
    elif tc_face >= anchor * 0.9:
        position = "near_anchor"
    else:
        position = "below_anchor"

    return {
        "cash_sgd": round(cash_sgd),
        "equity_face_sgd": round(equity_face_sgd),
        "tc_face_sgd": round(tc_face),
        "tc_discounted_sgd": round(tc_discounted),
        "anchor_sgd": anchor,
        "gap_vs_anchor_pct": round(gap_pct * 100, 1),
        "position": position,
        "note": "参考评估，非闸门（policy v2：先保底再谈判）",
    }


def vs_reference_city(policy: dict[str, Any], city: str,
                      tc: float, currency: str) -> dict[str, Any]:
    """搬迁机会对照参考换算线（v2：信息参考，非一票否决）。"""
    refs = policy.get("reference_conversions", {})
    if city not in refs:
        raise KeyError(f"reference_conversions 无城市 {city}（可选：{sorted(refs)}）")
    ref = refs[city]
    tc_sgd = to_sgd(tc, currency, policy["fx"])
    return {
        "city": city,
        "tc_sgd_equiv": round(tc_sgd),
        "reference_sgd": ref["sgd_equiv"],
        "meets_reference": tc_sgd >= ref["sgd_equiv"],
        "note": "换算参考线，非走人线判决；对外永不披露",
    }
