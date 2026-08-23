"""Event Log — append-only JSONL，唯一事实源（DESIGN P3 / ADR-1）。

P0 形态：单文件、单进程、无锁。重放 = 重建投影 = 回归测试。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

SGT = timezone(timedelta(hours=8))


class EventLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        kind: str,
        source: str,
        payload: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "ts": ts or datetime.now(SGT).isoformat(timespec="seconds"),
            "kind": kind,
            "source": source,
            "payload": payload or {},
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def tail(self, n: int) -> list[dict[str, Any]]:
        return list(self.events())[-n:]

    def count(self) -> int:
        return sum(1 for _ in self.events())
