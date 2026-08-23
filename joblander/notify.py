"""本地通知（macOS osascript）。打扰预算（ADR-12）：只推晨报/面前弹药/新提案聚合，永不催办。"""

from __future__ import annotations

import subprocess
import sys


def notify(title: str, message: str, url: str | None = None) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        script = f'display notification "{message[:180]}" with title "joblander" subtitle "{title[:60]}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
        return True
    except Exception:
        return False
