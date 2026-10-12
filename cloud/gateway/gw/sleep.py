"""闲置休眠：用户 machine 没人用就挂起（suspend，恢复约几百毫秒），省掉 24 小时常开的机器钱。

- 睡：IDLE 分钟没有请求，且引擎 /api/busy 说没在跑任务（用户点的或定时 job）→ suspend；suspend 不了就 stop。
  Fly 不建议同时挂起一大批，每轮最多挂 PER_TICK 台。
- 醒：用户来请求 → 先 start 再转发（同一个人的并发请求共用一把锁）；
  定时 job 的点（夜扫 02:30、晨报 08:15、日记 21:30、周日周报 20:00）稍后统一叫醒一轮，
  引擎的调度器会补跑当天到点没跑的 job，跑完照常闲置再睡。
- 网关重启后不知道谁在睡：启动时问一遍 Fly；转发连不上时也会查一次状态、该叫醒就叫醒。

只有内存状态；丢了也无妨，最坏情况是多问一次 Fly。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from gw.flyapi import Fly, FlyError
from gw.store import Store, User

log = logging.getLogger("uvicorn.error")

PER_TICK = 3
WAKE_WINDOW = 30 * 60          # 网关在叫醒点之后这么久内启动，也补叫一次
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_wake(spec: str) -> list[tuple[int | None, int, int]]:
    """"02:35,08:20,sun 20:05" → [(None, 2, 35), (None, 8, 20), (6, 20, 5)]（星期 None = 每天）。"""
    out = []
    for part in filter(None, (p.strip().lower() for p in spec.split(","))):
        day, _, hm = part.rpartition(" ")
        h, m = hm.split(":")
        out.append((DAYS.index(day) if day else None, int(h), int(m)))
    return out


class Sleeper:
    def __init__(self, store: Store, fly: Fly, http: httpx.AsyncClient, *, idle_minutes: int,
                 wake_at: str, tz: str, now: float | None = None):
        self.store, self.fly, self.http = store, fly, http
        self.idle = idle_minutes * 60
        self.wake_at = parse_wake(wake_at)
        self.tz = ZoneInfo(tz)
        self.asleep: set[str] = set()
        self.last_seen: dict[str, float] = {}
        self.started_at = now or time.time()
        self.fired: set[str] = set()
        self.locks: dict[str, asyncio.Lock] = {}

    def seen(self, email: str, now: float | None = None) -> None:
        self.last_seen[email] = now or time.time()

    # ---------- 醒 ----------

    async def _start(self, user: User) -> None:
        async with self.locks.setdefault(user.email, asyncio.Lock()):
            if user.email not in self.asleep:
                return
            try:
                await self.fly.start_machine(user.machine_id)
            except FlyError as e:                       # 已经在跑（比如升级时被 update 拉起来）就算醒了
                if "already" not in str(e).lower() and "412" not in str(e):
                    state = await self.fly.machine_state(user.machine_id)
                    if state != "started":
                        raise
            await self.fly.wait_started(user.machine_id)
            self.asleep.discard(user.email)
            self.seen(user.email)

    async def ensure_awake(self, user: User) -> None:
        """转发前调用：在睡就叫醒。"""
        if user.email in self.asleep:
            await self._start(user)

    async def recover(self, user: User) -> bool:
        """转发连不上时调用：机器其实在睡（网关重启后不知道）就叫醒，返回是否该重试一次。"""
        try:
            state = await self.fly.machine_state(user.machine_id)
        except FlyError:
            return False
        if state in ("stopped", "suspended"):
            self.asleep.add(user.email)
            await self._start(user)
            return True
        return False

    # ---------- 睡 ----------

    async def _busy(self, user: User) -> bool | None:
        try:
            r = await self.http.get(f"http://{self.fly.address(user.machine_id)}:8899/api/busy",
                                    headers={"x-joblander-gateway": user.gateway_token}, timeout=5)
            return bool(r.json().get("busy")) if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    async def _suspend(self, user: User) -> None:
        try:
            await self.fly.suspend_machine(user.machine_id)
        except FlyError as e:                            # 老机器不支持挂起：退一步关机（醒来是冷启动，慢几秒）
            log.info("suspend failed, stopping instead: %s", str(e)[:120])
            await self.fly.stop_machine(user.machine_id)
        self.asleep.add(user.email)

    async def reap(self, now: float) -> list[str]:
        if not self.idle:
            return []
        slept = []
        for user in self.store.ready_users():
            if len(slept) >= PER_TICK:
                break
            e = user.email
            if e in self.asleep or now - self.last_seen.get(e, self.started_at) < self.idle:
                continue
            busy = await self._busy(user)
            if busy is None:                             # 问不到（可能已经停了）：这轮先不动
                continue
            if busy:
                self.seen(e, now)                        # 在干活：再等一个 IDLE
                continue
            try:
                await self._suspend(user)
                slept.append(e)
            except FlyError as err:
                log.warning("sleep failed: %s", str(err)[:200])
        return slept

    # ---------- 定时叫醒 ----------

    def due_wakes(self, now: float) -> list[str]:
        local = datetime.fromtimestamp(now, self.tz)
        due = []
        for wd, h, m in self.wake_at:
            for back in (0, 1):                          # 跨午夜的窗口：也看昨天的点
                d = (local - timedelta(days=back)).replace(hour=h, minute=m, second=0, microsecond=0)
                key = f"{d:%Y-%m-%d} {h:02d}:{m:02d}"
                if (wd is None or d.weekday() == wd) and 0 <= now - d.timestamp() < WAKE_WINDOW \
                        and key not in self.fired:
                    self.fired.add(key)
                    due.append(key)
        return due

    async def wake_all(self) -> int:
        n = 0
        for user in self.store.ready_users():
            if user.email in self.asleep:
                try:
                    await self._start(user)
                    n += 1
                except FlyError as e:
                    log.warning("scheduled wake failed: %s", str(e)[:200])
                await asyncio.sleep(1)                   # 别一下子全拉起来
        return n

    # ---------- 主循环 ----------

    async def init(self) -> None:
        """网关刚启动：问 Fly 谁已经在睡。"""
        for user in self.store.ready_users():
            try:
                if await self.fly.machine_state(user.machine_id) in ("stopped", "suspended"):
                    self.asleep.add(user.email)
            except FlyError:
                pass

    async def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        if self.due_wakes(now):
            n = await self.wake_all()
            log.info("scheduled wake: %d machine(s)", n)
        slept = await self.reap(now)
        if slept:
            log.info("put %d idle machine(s) to sleep", len(slept))

    async def run(self, interval: int = 60) -> None:
        if not self.idle:
            return
        await self.init()
        while True:
            try:
                await self.tick()
            except Exception as e:                       # noqa: BLE001  循环不能死
                log.warning("sleeper tick failed: %s", str(e)[:200])
            await asyncio.sleep(interval)
