"""Sentinel — 口径宪兵：规则层（DESIGN §7.7 / ADR-4）。

本文件只实现规则**类型**（pattern / precision / pair）；规则**实例**（真实词表与数字）
全部来自私有 config——公开引擎不含任何红线内容（DESIGN §13 公私边界）。

设计轴（sentinel v2）：从「能不能说」改为「谁先说 + 说到多准」——
规则层管精确性与硬红线，判断层（P1，LLM）管叙事时机与跨场次一致性。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Action(str, Enum):
    BLOCK = "block"
    WARN = "warn"
    PASS = "pass"


class Audience(str, Enum):
    OUTBOUND = "outbound"   # 会被对方看到的文本（消息草稿、表单、简历段落）
    INTERNAL = "internal"   # 本地制品（brief、复盘）——默认只标注不拦截


@dataclass
class Finding:
    rule_id: str
    action: Action
    excerpt: str
    why: str = ""
    guidance: str = ""


@dataclass
class Verdict:
    findings: list[Finding] = field(default_factory=list)

    @property
    def action(self) -> Action:
        if any(f.action == Action.BLOCK for f in self.findings):
            return Action.BLOCK
        if any(f.action == Action.WARN for f in self.findings):
            return Action.WARN
        return Action.PASS

    def explain(self) -> str:
        if not self.findings:
            return "PASS"
        lines = [f"{self.action.value.upper()}:"]
        for f in self.findings:
            lines.append(f"  [{f.rule_id}] 命中「{f.excerpt}」 {f.why}")
            if f.guidance:
                lines.append(f"    → {f.guidance}")
        return "\n".join(lines)


def _search(patterns: list[str], text: str) -> re.Match | None:
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m
    return None


class Sentinel:
    """规则引擎。用法：Sentinel.from_config(cfg).check(text)"""

    def __init__(self, rules: list[dict[str, Any]]):
        self.rules = rules

    @classmethod
    def from_config(cls, cfg) -> "Sentinel":
        return cls(cfg.sentinel_rules)

    def check(self, text: str, audience: Audience = Audience.OUTBOUND) -> Verdict:
        findings = []
        for rule in self.rules:
            # outbound 永远适用全部规则；internal 只适用显式声明 internal 的规则
            if audience is Audience.INTERNAL and "internal" not in rule.get("audiences", ["outbound"]):
                continue
            f = self._apply(rule, text)
            if f is not None:
                if audience is Audience.INTERNAL and f.action is Action.BLOCK:
                    # 内部制品：拦截降级为标注（v2：出现在内部制品则标注）
                    f = Finding(f.rule_id, Action.WARN, f.excerpt, f.why, f.guidance)
                findings.append(f)
        return Verdict(findings)

    def _apply(self, rule: dict[str, Any], text: str) -> Finding | None:
        rtype = rule.get("type", "pattern")
        action = Action(rule.get("action", "block"))
        why = rule.get("why", "")
        guidance = rule.get("guidance", "")

        if rtype == "pattern":
            m = _search(rule.get("patterns", []), text)
            if m:
                return Finding(rule["id"], action, m.group(0), why, guidance)

        elif rtype == "precision":
            # 漂移即事实错误 → 恒为 block；合规精确值不触发
            m = _search(rule.get("drift_patterns", []), text)
            if m:
                exact = rule.get("exact_note", "")
                return Finding(rule["id"], Action.BLOCK, m.group(0), why, f"精确值：{exact}")

        elif rtype == "pair":
            window = int(rule.get("window", 120))
            for p in rule.get("anchor_patterns", []):
                for m in re.finditer(p, text, flags=re.IGNORECASE):
                    lo = max(0, m.start() - window)
                    hi = min(len(text), m.end() + window)
                    ctx = text[lo:hi]
                    if _search(rule.get("forbidden_nearby", []), ctx):
                        return Finding(rule["id"], action, ctx.strip()[:80], why,
                                       guidance or "总包口径不得与「到手」连用")
                    required = rule.get("required_nearby", [])
                    if required and not _search(required, ctx):
                        return Finding(rule["id"], action, ctx.strip()[:80], why,
                                       guidance or "报总包必须带 base+bonus+equity 拆解")
            m = _search(rule.get("extra_warn_patterns", []), text)
            if m:
                return Finding(rule["id"], Action.WARN, m.group(0), why,
                               rule.get("extra_warn_guidance", "对外统一使用报价锚点口径"))

        return None
