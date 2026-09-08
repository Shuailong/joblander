"""Event Log — append-only JSONL，唯一事实源（DESIGN P3 / ADR-1）。

P0 形态：单文件、单进程、无锁。重放 = 重建投影 = 回归测试。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

from joblander.tz import LOCAL_TZ as SGT   # 单一来源，JOBLANDER_TZ 可覆盖


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

    def iter_reversed(self, chunk: int = 64 * 1024) -> Iterator[dict[str, Any]]:
        """从文件尾往回读，逐条 yield（新→旧）。

        日志只增不减。此前「取最近 N 条」「找最后一条某类事件」都是
        list(events())——把整份日志materialize 进内存再切片，成本随使用时间
        线性增长且永不回落。倒着读 + 早停，代价只跟真正要看的条数有关。"""
        if not self.path.exists():
            return
        with open(self.path, "rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            buf = b""
            while pos > 0:
                step = min(chunk, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                parts = buf.split(b"\n")
                buf = parts.pop(0)          # 首段可能是半行，留给下一轮拼
                for raw in reversed(parts):
                    raw = raw.strip()
                    if raw:
                        try:
                            yield json.loads(raw.decode("utf-8"))
                        except Exception:
                            continue
            raw = buf.strip()
            if raw:
                try:
                    yield json.loads(raw.decode("utf-8"))
                except Exception:
                    pass

    def last(self, kind: str) -> dict[str, Any] | None:
        """最后一条某类事件；命中即停，不读整份日志。"""
        return next((e for e in self.iter_reversed() if e.get("kind") == kind), None)

    def tail(self, n: int) -> list[dict[str, Any]]:
        out = []
        for e in self.iter_reversed():
            out.append(e)
            if len(out) >= n:
                break
        out.reverse()                       # 对外仍是旧→新
        return out

    def count(self) -> int:
        return sum(1 for _ in self.events())
