"""隐私 v2 的行为数据：网关这边发「会话」事件，引擎那边发「请求」事件，都进 Pub/Sub → BigQuery。

只对开着开关、且已过退出期的用户采集（规则见 privacy_v2.analytics_allowed）。
事件里认人只用 user_key（加盐哈希，与引擎 joblander/obs.py 同一算法），不放邮箱；
不放任何内容：会话事件是 IP、城市级位置、设备与浏览器；请求事件是页面模板、状态码、耗时。

领头实例每天跑一次清理（Sweeper），兑现隐私说明 v2 的保存期限：
- 关掉开关的用户、删除或重置了账户的用户：已采集的行为数据从 BigQuery 删掉（说明里承诺 30 天内）；
- 完整 IP 只留 90 天：BigQuery 里的会话事件与网关库里的「大致所在地」到期去掉 IP，只留城市级位置。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import Request

from gw.geo import client_ip

log = logging.getLogger("uvicorn.error")
METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
IP_DAYS = 90                         # 完整 IP 保留天数（之后只留城市级位置）
PURGED = "analytics_purged:"         # kv：某个 user_key 在哪次关闭之后已经清过
PENDING = "analytics_purge:"         # kv：删除 / 重置了的账户，等着清理的 user_key
SETTLE = 3600                        # 关掉 / 删除一小时后再清：路上还没写进 BigQuery 的事件也赶得上


def user_key(tenant_id: str, salt: str | None = None) -> str:
    salt = os.environ.get("JOBLANDER_LOG_SALT", "") if salt is None else salt
    return hashlib.sha256(f"{salt}:{tenant_id}".encode()).hexdigest()[:16]


def geo(request: Request) -> dict:
    """负载均衡器按 IP 推算的位置（自定义请求头：国家,省份,城市）。"""
    raw = request.headers.get("x-client-geo-location") or ""
    parts = [p.strip() for p in raw.split(",")]
    while len(parts) < 3:
        parts.append("")
    return {"country": parts[0], "region": parts[1], "city": ",".join(parts[2:]).strip(", ")}


def device(ua: str) -> dict:
    u = ua.lower()
    kind = "tablet" if ("ipad" in u or "tablet" in u) else "mobile" if ("mobi" in u or "android" in u) else "desktop"
    browser = ("edge" if "edg/" in u else "chrome" if "chrome/" in u or "crios" in u else
               "firefox" if "firefox/" in u or "fxios" in u else "safari" if "safari/" in u else "other")
    return {"device": kind, "browser": browser}


class Publisher:
    """攒一批再发：每 5 秒或攒满 500 条发一次。发不出去就丢（这是统计，不是账本）。"""

    def __init__(self, topic: str, client: httpx.AsyncClient | None = None):
        self.topic = topic
        self.http = client or httpx.AsyncClient(timeout=15)
        self.buf: list[dict] = []
        self._token: tuple[str, float] = ("", 0.0)
        self._task: asyncio.Task | None = None

    def emit(self, event: dict) -> None:
        if len(self.buf) < 5000:
            self.buf.append(event)
        if self._task is None or self._task.done():
            try:
                self._task = asyncio.get_running_loop().create_task(self._run())
            except RuntimeError:
                pass

    async def _access_token(self) -> str:
        tok, exp = self._token
        if tok and exp > time.time() + 60:
            return tok
        r = await self.http.get(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=5)
        r.raise_for_status()
        data = r.json()
        self._token = (data["access_token"], time.time() + int(data.get("expires_in", 300)))
        return self._token[0]

    async def flush(self) -> int:
        batch, self.buf = self.buf[:500], self.buf[500:]
        if not batch:
            return 0
        import base64
        body = {"messages": [{"data": base64.b64encode(json.dumps(e, ensure_ascii=False).encode()).decode()}
                             for e in batch]}
        try:
            r = await self.http.post(f"https://pubsub.googleapis.com/v1/{self.topic}:publish", json=body,
                                     headers={"Authorization": f"Bearer {await self._access_token()}"})
            r.raise_for_status()
        except Exception as e:                                  # noqa: BLE001
            log.warning("行为事件发送失败（丢弃 %d 条）：%s", len(batch), e)
            return 0
        return len(batch)

    async def _run(self) -> None:
        while self.buf:
            await asyncio.sleep(5)
            await self.flush()


class SessionEvents:
    """每人每天第一次访问发一条会话事件（同一实例内去重；多实例偶有重复，分析时按天去重）。"""

    def __init__(self, publisher: Publisher, tz: str = "Asia/Singapore"):
        self.pub = publisher
        self.tz = ZoneInfo(tz)
        self.seen: set[tuple[str, str]] = set()

    def on_request(self, tenant_id: str, request: Request, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        key = user_key(tenant_id)
        day = datetime.fromtimestamp(now, self.tz).strftime("%Y-%m-%d")
        if (key, day) in self.seen:
            return False
        self.seen.add((key, day))
        if len(self.seen) > 100_000:                          # 跨天后老的条目没用了
            self.seen = {k for k in self.seen if k[1] == day}
        self.pub.emit({"v": 1, "type": "session", "user_key": key, "at": now, "ip": client_ip(request),
                       **geo(request), **device(request.headers.get("user-agent") or "")})
        return True


def forget(store, tenant_id: str | None) -> None:
    """账户删除或重置时调用：这个账户（旧的账户号）的行为数据排进清理队列。只存 user_key，不存邮箱。"""
    if not tenant_id:
        return
    key = user_key(tenant_id)
    store.del_kv(PURGED + key)
    store.set_kv(PENDING + key, str(time.time()))


class Sweeper:
    """每天一次（领头实例跑）：清掉该删的行为数据、到期的完整 IP。table 为空时只处理网关库里的 IP。"""

    def __init__(self, store, table: str | None, leader=None, client: httpx.AsyncClient | None = None,
                 publisher: Publisher | None = None):
        self.store, self.table, self.leader = store, table, leader
        self.http = client or httpx.AsyncClient(timeout=90)
        self.pub = publisher or Publisher("", self.http)       # 只借它拿访问令牌

    async def _query(self, sql: str, params: dict[str, str] | None = None) -> bool:
        """跑一条 DML；没跑完或出错都算失败（明天再来，语句本身可以重复跑）。"""
        project = (self.table or "").split(".")[0]
        q = {"query": sql, "useLegacySql": False, "timeoutMs": 60000}
        if params:
            q["parameterMode"] = "NAMED"
            q["queryParameters"] = [{"name": k, "parameterType": {"type": "STRING"}, "parameterValue": {"value": v}}
                                    for k, v in params.items()]
        r = await self.http.post(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries", json=q,
                                 headers={"Authorization": f"Bearer {await self.pub._access_token()}"})
        if r.status_code >= 300:
            log.warning("BigQuery 清理失败（%s）：%s", r.status_code, r.text[:300])
            return False
        data = r.json()
        return bool(data.get("jobComplete")) and not data.get("errors")

    async def purge(self, key: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{16}", key):
            return False
        return await self._query(f"DELETE FROM `{self.table}` WHERE JSON_VALUE(data, '$.user_key') = @k", {"k": key})

    async def truncate_ips(self) -> bool:
        return await self._query(
            f"UPDATE `{self.table}` SET data = JSON_REMOVE(data, '$.ip') "
            f"WHERE publish_time < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {IP_DAYS} DAY) "
            f"AND JSON_VALUE(data, '$.ip') IS NOT NULL")

    async def sweep(self, now: float | None = None) -> int:
        """返回这次清掉了几个人的行为数据。"""
        now = time.time() if now is None else now
        self.store.truncate_ips(now - IP_DAYS * 86400)
        if not self.table:
            return 0
        done = 0
        for u in self.store.analytics_off_users():
            if not u.volume_id or u.analytics_off > now - SETTLE:
                continue
            key = user_key(u.volume_id)
            if self.store.get_kv(PURGED + key) == str(u.analytics_off):
                continue                                         # 这次关闭之后已经清过了
            try:
                if await self.purge(key):
                    self.store.set_kv(PURGED + key, str(u.analytics_off))
                    done += 1
            except Exception as e:                               # noqa: BLE001  明天再试
                log.warning("清理行为数据失败 %s：%s", key, e)
        for k, at in self.store.kv_items(PENDING):
            if float(at) > now - SETTLE:
                continue
            key = k[len(PENDING):]
            try:
                if await self.purge(key):
                    self.store.del_kv(k)
                    done += 1
            except Exception as e:                               # noqa: BLE001
                log.warning("清理已删账户的行为数据失败 %s：%s", key, e)
        try:
            await self.truncate_ips()
        except Exception as e:                                   # noqa: BLE001
            log.warning("截断行为数据里的 IP 失败：%s", e)
        return done

    async def run(self) -> None:
        while True:
            if self.leader is None or self.leader.ok():
                try:
                    await self.sweep()
                except Exception as e:                           # noqa: BLE001  别让清理循环退出
                    log.warning("每日清理出错：%s", e)
            await asyncio.sleep(86400)
