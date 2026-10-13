"""后台任务登记表：长 LLM 作业不锁页面（托盘可见、切页不丢、完成即提醒）。

任务按账户分开登记——多租户下一个账户的托盘里绝不能出现另一个账户的任务。
- 本机 / Fly：内存登记表，重启即清（产物都已落盘，状态可丢）。
- 多租户：登记在数据库 tasks 表（按账户行级隔离），任何实例都能查到进度；任务在接单的实例上
  以后台线程执行（服务开着「CPU 常驻」），每 30 秒心跳——实例被回收导致心跳断了 3 分钟，
  托盘显示「任务中断，请重试」，不会永远转圈。
  这类任务会花 AI 额度、往时间线追加条目，不能自动重试；能安全重放的定时作业另走 Cloud Tasks（见 cloud/）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import MutableMapping
from typing import Any, Callable, Iterator

from joblander import runtime
from joblander.tenancy import in_context, tenant_id

HEARTBEAT = 30
STALE = 180
RECENT = 120
LOST = "任务中断：服务重启或实例被回收，请重试"


class MemoryTable:
    def __init__(self) -> None:
        self._d: dict[str, dict[str, dict]] = {}
        self._lock = threading.Lock()

    def put(self, tenant: str, task: dict) -> None:
        with self._lock:
            self._d.setdefault(tenant, {})[task["id"]] = task

    def update(self, tenant: str, tid: str, **fields: Any) -> None:
        with self._lock:
            t = self._d.get(tenant, {}).get(tid)
            if t is not None:
                t.update(fields)

    def get(self, tenant: str, tid: str) -> dict | None:
        with self._lock:
            return self._d.get(tenant, {}).get(tid)

    def delete(self, tenant: str, tid: str) -> None:
        with self._lock:
            self._d.get(tenant, {}).pop(tid, None)

    def all(self, tenant: str) -> list[dict]:
        with self._lock:
            return list(self._d.get(tenant, {}).values())

    def clear(self, tenant: str) -> None:
        with self._lock:
            self._d.pop(tenant, None)


class PgTable:
    """tasks 表（见 storage/pg.py）。只回看一天内的任务。"""

    COLS = {"started": "started_at", "ended": "ended_at", "heartbeat": "heartbeat_at",
            "status": "status", "result": "result", "error": "error", "label": "label"}

    def __init__(self, store: Any):
        self.store = store

    @staticmethod
    def _row(r: tuple) -> dict:
        return {"id": r[0], "kind": r[1], "label": r[2], "status": r[3],
                "result": r[4], "error": r[5] or "", "started": r[6], "ended": r[7], "heartbeat": r[8]}

    def put(self, tenant: str, task: dict) -> None:
        with self.store.tx(tenant) as conn:
            conn.execute(
                "insert into tasks (tenant_id, id, kind, label, status, result, error, started_at, "
                "ended_at, heartbeat_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (tenant_id, id) do update set kind = excluded.kind, label = excluded.label, "
                "status = excluded.status, result = excluded.result, error = excluded.error, "
                "started_at = excluded.started_at, ended_at = excluded.ended_at, "
                "heartbeat_at = excluded.heartbeat_at",
                (tenant, task["id"], task.get("kind", ""), task.get("label", ""), task.get("status", ""),
                 json.dumps(task.get("result"), ensure_ascii=False, default=str),
                 task.get("error", ""), task.get("started") or time.time(), task.get("ended"),
                 task.get("heartbeat")))

    def update(self, tenant: str, tid: str, **fields: Any) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            col = self.COLS[k]
            sets.append(f"{col} = %s")
            vals.append(json.dumps(v, ensure_ascii=False, default=str) if k == "result" else v)
        with self.store.tx(tenant) as conn:
            conn.execute(f"update tasks set {', '.join(sets)} where tenant_id = %s and id = %s",
                         (*vals, tenant, tid))

    def get(self, tenant: str, tid: str) -> dict | None:
        with self.store.tx(tenant) as conn:
            r = conn.execute("select id, kind, label, status, result, error, started_at, ended_at, "
                             "heartbeat_at from tasks where tenant_id = %s and id = %s",
                             (tenant, tid)).fetchone()
        return self._row(r) if r else None

    def delete(self, tenant: str, tid: str) -> None:
        with self.store.tx(tenant) as conn:
            conn.execute("delete from tasks where tenant_id = %s and id = %s", (tenant, tid))

    def all(self, tenant: str) -> list[dict]:
        with self.store.tx(tenant) as conn:
            rows = conn.execute("select id, kind, label, status, result, error, started_at, ended_at, "
                                "heartbeat_at from tasks where tenant_id = %s and started_at > %s "
                                "order by started_at", (tenant, time.time() - 86400)).fetchall()
        return [self._row(r) for r in rows]

    def clear(self, tenant: str) -> None:
        with self.store.tx(tenant) as conn:
            conn.execute("delete from tasks where tenant_id = %s", (tenant,))


_table: Any = MemoryTable()


def set_table(table: Any) -> None:
    global _table
    _table = table


def table() -> Any:
    return _table


def start(kind: str, label: str, fn: Callable[[], Any], on_error: Callable[[str], None] | None = None) -> str:
    tid = uuid.uuid4().hex[:8]
    tenant = tenant_id()
    now = time.time()
    _table.put(tenant, {"id": tid, "kind": kind, "label": label, "status": "running",
                        "started": now, "result": None, "error": "", "heartbeat": now})
    sync = bool(os.environ.get("JOBLANDER_TASKS_SYNC"))
    beat = runtime.is_multi() and not sync

    def run() -> None:
        stop = threading.Event()
        if beat:
            def heartbeat() -> None:
                while not stop.wait(HEARTBEAT):
                    _table.update(tenant, tid, heartbeat=time.time())
            threading.Thread(target=heartbeat, daemon=True, name=f"task-hb-{tid}").start()
        try:
            result = fn()
            _table.update(tenant, tid, status="done", result=result, ended=time.time())
        except Exception as e:                      # noqa: BLE001  失败入托盘 + 事件日志，不静默
            _table.update(tenant, tid, status="error", error=str(e), ended=time.time())
            from joblander.obs import log_event
            log_event("task_failed", "WARNING", kind=kind, error=str(e))
            if on_error:
                try:
                    on_error(str(e))
                except Exception:
                    pass
        finally:
            stop.set()

    if sync:                                        # 测试 / 脚本：内联执行同一条链路
        run()
    else:
        threading.Thread(target=in_context(run), daemon=True, name=f"task-{kind}").start()
    return tid


def recent() -> list[dict]:
    """托盘：进行中的，加上 2 分钟内结束的。多租户下心跳断太久的标为中断。"""
    now = time.time()
    out = []
    for t in _table.all(tenant_id()):
        if (runtime.is_multi() and t.get("status") == "running"
                and now - (t.get("heartbeat") or t.get("started") or now) > STALE):
            _table.update(tenant_id(), t["id"], status="error", error=LOST, ended=now)
            t = {**t, "status": "error", "error": LOST, "ended": now}
        if t.get("status") == "running" or now - (t.get("ended") or now) < RECENT:
            out.append(t)
    return out


def running_kinds() -> list[str]:
    return [t.get("kind", "") for t in recent() if t.get("status") == "running"]


class TaskView(MutableMapping):
    """当前账户的任务，按 dict 用（兼容 web 层与测试里对 TASKS 的既有用法）。"""

    def __getitem__(self, tid: str) -> dict:
        t = _table.get(tenant_id(), tid)
        if t is None:
            raise KeyError(tid)
        return t

    def __setitem__(self, tid: str, task: dict) -> None:
        _table.put(tenant_id(), {**task, "id": tid})

    def __delitem__(self, tid: str) -> None:
        if _table.get(tenant_id(), tid) is None:
            raise KeyError(tid)
        _table.delete(tenant_id(), tid)

    def __iter__(self) -> Iterator[str]:
        return iter([t["id"] for t in _table.all(tenant_id())])

    def __len__(self) -> int:
        return len(_table.all(tenant_id()))

    def clear(self) -> None:
        _table.clear(tenant_id())


TASKS = TaskView()
