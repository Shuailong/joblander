"""W4 薪酬调研：统计层纯函数 + 报告端到端（MCF mock）+ web 端点。"""

from __future__ import annotations

import json

import pytest

from joblander.compensation import build_comp_report, collect_market, salary_stats
from joblander.config import Config

MCF_JOBS = [
    {"uuid": "u1", "title": "AI Engineer", "postedCompany": {"name": "Alpha"},
     "salary": {"minimum": 8000, "maximum": 12000, "type": {"salaryType": "Monthly"}}},
    {"uuid": "u2", "title": "LLM Engineer", "postedCompany": {"name": "Beta"},
     "salary": {"minimum": 10000, "maximum": 16000, "type": {"salaryType": "Monthly"}}},
    {"uuid": "u3", "title": "ML Intern", "postedCompany": {"name": "Gamma"},
     "salary": {"minimum": 1200, "maximum": 1800, "type": {"salaryType": "Monthly"}}},
    {"uuid": "u4", "title": "No Salary Role", "postedCompany": {"name": "Delta"},
     "salary": {}},
    {"uuid": "u5", "title": "Annual Guy", "postedCompany": {"name": "Eps"},
     "salary": {"minimum": 100000, "maximum": 150000, "type": {"salaryType": "Annually"}}},
]


@pytest.fixture
def cfg(tmp_path):
    ws = tmp_path / "ws"
    (ws / "03-materials").mkdir(parents=True)
    (ws / "03-materials" / "achievement-bank.md").write_text(
        "## LLM 平台\n把 agent 平台从 0 做到 1。", encoding="utf-8")
    (ws / "02-targets").mkdir()
    (ws / "02-targets" / "sourcing-prefs.yaml").write_text(
        "keywords: [AI Engineer]\n", encoding="utf-8")
    return Config(raw={"workspace_dir": str(ws),
                       "policy": {"base_floor_monthly": 10000}},
                  path=tmp_path / "c.yaml")


def test_collect_market_filters(monkeypatch):
    """只收月薪岗；无薪资/年薪/重复 uuid 丢弃。"""
    monkeypatch.setattr("joblander.sourcing.mcf_search",
                        lambda kw, limit=30: MCF_JOBS)
    rows = collect_market(["ai engineer", "llm"])          # 两个词命中同批 → uuid 去重
    assert [r["uuid"] if "uuid" in r else r["title"] for r in rows]
    assert len(rows) == 3
    assert all(r["mid"] > 0 for r in rows)
    assert {r["title"] for r in rows} == {"AI Engineer", "LLM Engineer", "ML Intern"}


def test_salary_stats_quantiles():
    rows = [{"kw": "a", "mid": m} for m in (8000, 10000, 12000, 14000)]
    s = salary_stats(rows)
    assert s["all"]["n"] == 4 and s["all"]["median"] == 11000
    assert s["by_kw"]["a"]["p25"] <= s["by_kw"]["a"]["median"] <= s["by_kw"]["a"]["p75"]


def test_build_comp_report_end_to_end(cfg, monkeypatch):
    """报告：日期头 + 零 LLM 统计表 + 锚点只出百分比 + 叙事 + 样本清单。"""
    monkeypatch.setattr("joblander.sourcing.mcf_search",
                        lambda kw, limit=30: MCF_JOBS)
    seen = {}

    class L:
        def generate(self, prompt, system=None, json_mode=False):
            seen["prompt"] = prompt
            return "## 市场概览\n供给集中在 agent 平台方向。"
    out = build_comp_report(cfg, L(), notes="群里说某厂 band 上调")
    text = out.read_text(encoding="utf-8")
    assert "# 薪酬调研 ·" in text and "关键词：AI Engineer" in text
    assert "| 方向 | 样本 |" in text and "SGD/月" in text          # 统计表
    assert "你的月 base 底线" in text and "10000" not in text.replace("10,000", "")  # 底线绝对值不上屏
    assert "%" in text.split("对照个人底线")[1][:120]
    assert "市场概览" in text and "样本清单" in text
    assert "LLM 平台" in seen["prompt"] and "群里说某厂" in seen["prompt"]


def test_build_comp_report_no_keywords(cfg, monkeypatch):
    (cfg.workspace_dir / "02-targets" / "sourcing-prefs.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        build_comp_report(cfg, None, keywords=None)
