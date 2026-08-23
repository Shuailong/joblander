"""Sentinel 金标回归 —— 吃私有 workspace 的 seeded violations（M4 种子，16 条）。

无私有 config / 种子文件时整体 skip（公开 CI 安全）。
这是「eval 与系统同生」（P5/ADR-5）的第一个落地：规则或词表任何变更必须过这 16 条。
"""

from pathlib import Path

import pytest
import yaml

from joblander.config import ConfigError, load_config
from joblander.sentinel import Action, Sentinel

SEEDS_REL = "migration/m4-golden-seeds/sentinel-seeded-violations.yaml"


def _load_cases():
    try:
        cfg = load_config()
    except ConfigError:
        return None, []
    seeds = cfg.workspace_dir / SEEDS_REL
    if not seeds.exists():
        return cfg, []
    with open(seeds, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return cfg, data.get("cases", [])


CFG, CASES = _load_cases()

pytestmark = pytest.mark.skipif(not CASES, reason="私有 config/golden seeds 不存在（公开环境跳过）")


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:24] for c in CASES] if CASES else [])
def test_seeded_violation(case):
    sentinel = Sentinel.from_config(CFG)
    verdict = sentinel.check(case["text"])
    expected = Action(case["expect"]) if case["expect"] != "pass" else Action.PASS
    assert verdict.action is expected, (
        f"期望 {case['expect']}，实得 {verdict.action.value}\n{verdict.explain()}"
    )
    if case.get("rule"):
        assert any(f.rule_id == case["rule"] for f in verdict.findings), (
            f"期望命中规则 {case['rule']}，实际命中 {[f.rule_id for f in verdict.findings]}"
        )
