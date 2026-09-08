"""本地时区 —— 全项目单一来源。

历史上 28 个模块各写一遍 `SGT = timezone(timedelta(hours=8))`：作者在新加坡，
于是「今天」的边界、日报/周报文件名、daemon 的 08:15 / 21:30 / 02:30 全钉死在
UTC+8。其他时区的用户拿到的是一套对不上自己一天的时钟。

为什么走环境变量而不是 config.yaml：这些是模块级常量，import 时就要定值，
而配置要等 load_config() 才有（还可能根本不存在）。`JOBLANDER_TZ` 支持
IANA 名（Asia/Singapore、Europe/Berlin）或固定偏移（+08:00、-05:00）。
不设则保持 UTC+8，与历史行为完全一致。
"""

from __future__ import annotations

import os
import re
from datetime import timedelta, timezone

_DEFAULT = timezone(timedelta(hours=8))
_OFFSET = re.compile(r"^([+-])(\d{1,2}):?(\d{2})?$")


def _resolve(spec: str | None):
    if not spec:
        return _DEFAULT
    spec = spec.strip()
    m = _OFFSET.match(spec)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        hours, minutes = int(m.group(2)), int(m.group(3) or 0)
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:                                    # IANA 名（Python 3.9+ 自带 zoneinfo）
        from zoneinfo import ZoneInfo
        return ZoneInfo(spec)
    except Exception:                       # 名字打错不该让整个程序起不来
        return _DEFAULT


LOCAL_TZ = _resolve(os.environ.get("JOBLANDER_TZ"))
