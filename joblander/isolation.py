"""隔离违规：账户之间的边界被碰到时记一笔。正常运行中计数永远为 0。

输出一行结构化日志（Cloud Logging 按 severity 与 jsonPayload 解析），由日志指标
jl_isolation_violations_total 计数并触发 P1 告警，同时启动泄露评估流程（见 OPERATIONS）。
种类：rls（数据库行级安全拒绝）、decrypt（密文与账户 / 文件不匹配）、path（越出账户空间）、
token（账户令牌无效或与请求不符）。
"""

from __future__ import annotations

import json
import sys
import threading

_lock = threading.Lock()
_counts: dict[str, int] = {}


def violation(kind: str, detail: str = "") -> None:
    with _lock:
        _counts[kind] = _counts.get(kind, 0) + 1
    print(json.dumps({"severity": "ERROR", "event": "isolation_violation", "kind": kind,
                      "detail": detail[:200]}, ensure_ascii=False), file=sys.stderr, flush=True)


def counts() -> dict[str, int]:
    with _lock:
        return dict(_counts)
