"""本地通知（macOS osascript）。打扰预算（ADR-12）：只推晨报/面前弹药/新提案聚合，永不催办。"""

from __future__ import annotations

import subprocess
import sys


def _as_str(s: str) -> str:
    """AppleScript 字符串字面量转义。

    通知内容里有公司名与日历标题，而它们来自 LLM 对邮件的抽取——等于把外部文本
    拼进 osascript 源码。一个含 `" & (do shell script "…") & "` 的公司名即可越出
    字符串执行命令。反斜杠必须先转，否则会把后加的转义再拆开。"""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, url: str | None = None) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        script = (f'display notification "{_as_str(message[:180])}" '
                  f'with title "joblander" subtitle "{_as_str(title[:60])}" '
                  f'sound name "Glass"')
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
        return True
    except Exception:
        return False
