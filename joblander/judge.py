"""Sentinel 判断层（P1 v0）— 规则层拦不住的：叙事时机、一致性、语义漂移。

检查清单来自私有 config（sentinel.judgment_checks）；LLM 逐条判定 ok/attention。
"""

from __future__ import annotations

import json

JUDGE_SYSTEM = """你是求职口径守卫的判断层。输入一段将要对外使用的文本（或内部 brief），以及检查清单。
对每条检查输出判定。输出严格 JSON：
{"findings": [{"check": "清单原文", "verdict": "ok|attention", "note": "一句话，attention 必须给具体位置或原文引用"}]}
纪律：拿不准判 attention 并说明；不逐条复述无关内容。"""


def judge(cfg, llm, text: str, context_note: str = "") -> list[dict]:
    from joblander.scribe import _strip_fences

    checks = cfg.raw.get("sentinel", {}).get("judgment_checks", [])
    if not checks:
        return []
    prompt = (f"场景：{context_note or '通用对外文本'}\n"
              f"检查清单：\n" + "\n".join(f"- {c}" for c in checks) +
              f"\n\n待检文本：\n{text[:30000]}")
    raw = llm.generate(prompt, system=JUDGE_SYSTEM, json_mode=True)
    return json.loads(_strip_fences(raw)).get("findings", [])
