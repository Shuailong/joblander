"""运维事件：一行结构化 JSON 打到标准输出，Cloud Logging 自动解析（severity / jsonPayload）。

只放「运营要知道的事」——任务失败、调度作业失败、上游出错——不放任何用户内容：
账户只记哈希后的 user_key，错误信息截断到 300 字。日志指标与告警按 event 字段筛选（见 infra/）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any


def user_key(tenant_id: str) -> str:
    salt = os.environ.get("JOBLANDER_LOG_SALT", "")
    return hashlib.sha256(f"{salt}:{tenant_id}".encode()).hexdigest()[:16]


def log_event(event: str, severity: str = "INFO", **fields: Any) -> None:
    from joblander import runtime
    if not runtime.is_multi():
        return                                  # 本机版不往标准输出打运维日志
    from joblander.tenancy import tenant_id
    rec = {"severity": severity, "event": event, "user_key": user_key(tenant_id())}
    for k, v in fields.items():
        rec[k] = v[:300] if isinstance(v, str) else v
    print(json.dumps(rec, ensure_ascii=False, default=str), file=sys.stdout, flush=True)
