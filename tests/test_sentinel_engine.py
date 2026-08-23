"""Sentinel 引擎单测 —— 合成规则，公开可跑（不含真实红线内容）。"""

from joblander.sentinel import Action, Audience, Sentinel

RULES = [
    {"id": "codename", "type": "pattern", "action": "block",
     "patterns": ["ProjectX", "秘密系统"], "why": "内部代号"},
    {"id": "drift", "type": "precision",
     "drift_patterns": [r"around\s*99\s*[Kk]"], "exact_note": "98,765"},
    {"id": "pair", "type": "pair", "action": "warn",
     "anchor_patterns": [r"500\s*[Kk]"],
     "required_nearby": ["breakdown"], "forbidden_nearby": ["cash-in-hand"],
     "window": 40, "extra_warn_patterns": [r"512\s*[Kk]"]},
]


def make():
    return Sentinel(RULES)


def test_pattern_block():
    v = make().check("we built ProjectX last year")
    assert v.action is Action.BLOCK
    assert v.findings[0].rule_id == "codename"


def test_clean_text_passes():
    v = make().check("we built a routing system last year")
    assert v.action is Action.PASS
    assert v.findings == []


def test_precision_drift_blocks_with_exact_guidance():
    v = make().check("my base was around 99k")
    assert v.action is Action.BLOCK
    assert "98,765" in v.findings[0].guidance


def test_pair_missing_required_warns():
    v = make().check("I expect 500K total")
    assert v.action is Action.WARN


def test_pair_with_required_passes():
    v = make().check("I expect 500K total, breakdown: base plus bonus plus equity")
    assert v.action is Action.PASS


def test_pair_forbidden_warns_even_with_required():
    v = make().check("500K breakdown cash-in-hand")
    assert v.action is Action.WARN


def test_pair_extra_warn_number():
    v = make().check("maybe 512K works")
    assert v.action is Action.WARN


def test_internal_audience_skips_undeclared_rules():
    v = make().check("we built ProjectX", audience=Audience.INTERNAL)
    assert v.action is Action.PASS


def test_internal_audience_downgrades_block_to_warn():
    rules = [{"id": "codename", "type": "pattern", "action": "block",
              "audiences": ["outbound", "internal"], "patterns": ["ProjectX"]}]
    v = Sentinel(rules).check("ProjectX", audience=Audience.INTERNAL)
    assert v.action is Action.WARN
