"""Analyst 纯函数单测 —— 全合成数字（真实 policy 在私有 config，不入库）。"""

import pytest

from joblander.analyst import annual_cash, equity_annual_value, offer_snapshot, to_sgd, vs_reference_city

POLICY = {
    "quote_tc_sgd": 250000,
    "fx": {"EUR": 1.42, "GBP": 1.70, "AED": 0.351, "USD": 1.34, "RMB": 0.186, "SGD": 1.0},
    "equity_discount_factors": {"light": 1.0, "medium": 0.5, "heavy": 0.0},
    "reference_conversions": {
        "berlin": {"tc": 200000, "currency": "EUR", "sgd_equiv": 280000},
    },
}


def test_annual_cash_base_plus_bonus_months():
    # base + 月数制 bonus：15K × (12+2) = 210K
    assert annual_cash(15000, bonus_months=2) == 210000


def test_annual_cash_pct_bonus():
    # 年 base 180K + 15% = 207K
    assert annual_cash(180000 / 12, bonus_pct=0.15) == pytest.approx(207000)


def test_to_sgd_rmb():
    assert to_sgd(1_000_000, "RMB", POLICY["fx"]) == pytest.approx(186000)


def test_to_sgd_unknown_currency_raises():
    with pytest.raises(KeyError):
        to_sgd(100, "JPY", POLICY["fx"])


def test_equity_tiers():
    assert equity_annual_value(40000, "light") == 40000
    assert equity_annual_value(40000, "medium") == 20000
    assert equity_annual_value(40000, "heavy") == 0
    with pytest.raises(KeyError):
        equity_annual_value(40000, "unknown")


def test_offer_snapshot_equity_discount_split():
    # 15K base + 2 月 bonus + 40K 期权面值：面值 250K 达锚，heavy 折价后 210K
    snap = offer_snapshot(POLICY, base_monthly=15000, bonus_months=2,
                          equity_face_annual=40000, equity_tier="heavy")
    assert snap["tc_face_sgd"] == 250000
    assert snap["tc_discounted_sgd"] == 210000
    assert snap["position"] == "at_or_above_anchor"


def test_offer_snapshot_below_anchor():
    # 12K + 19% target ≈ 171K → below（低档 band 场景）
    snap = offer_snapshot(POLICY, base_monthly=12000, bonus_pct=0.19)
    assert snap["cash_sgd"] == 171360
    assert snap["position"] == "below_anchor"


def test_offer_snapshot_near_anchor_band():
    snap = offer_snapshot(POLICY, base_monthly=20000, bonus_pct=0.0)   # 240K = 96% of 250K
    assert snap["position"] == "near_anchor"


def test_vs_reference_city_is_info_not_gate():
    r = vs_reference_city(POLICY, "berlin", 200000, "EUR")
    assert r["tc_sgd_equiv"] == 284000
    assert r["meets_reference"] is True
    assert "非" in r["note"]          # 明示非闸门
    with pytest.raises(KeyError):
        vs_reference_city(POLICY, "tokyo", 1, "SGD")
