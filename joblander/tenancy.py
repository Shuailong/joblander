"""当前账户（租户）上下文。

多租户形态下，同一个进程同时替很多账户干活：每个请求 / 每个后台任务开始时把「这是谁」放进
contextvar，下游一律从这里取，而不是从模块级变量取——模块级状态是跨账户串数据最常见的来源。

本机版与 Fly 版只有一个账户（id 为 "local"），不需要显式设置：current_cfg() 回落到
set_default_config() 登记的那份配置，行为与改造前完全一致。
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

LOCAL_TENANT = "local"


@dataclass
class Tenant:
    id: str
    cfg: Any                     # joblander.config.Config


_current: contextvars.ContextVar[Tenant | None] = contextvars.ContextVar("joblander_tenant", default=None)
_default_cfg: Any = None


def set_default_config(cfg: Any) -> None:
    global _default_cfg
    _default_cfg = cfg


def current_tenant() -> Tenant | None:
    return _current.get()


def tenant_id() -> str:
    t = _current.get()
    return t.id if t else LOCAL_TENANT


def current_cfg() -> Any:
    t = _current.get()
    if t is not None:
        return t.cfg
    if _default_cfg is not None:
        return _default_cfg
    raise RuntimeError("没有当前账户：多租户形态下请求必须先经账户中间件")


@contextmanager
def use_tenant(t: Tenant) -> Iterator[Tenant]:
    token = _current.set(t)
    try:
        yield t
    finally:
        _current.reset(token)


class ConfigProxy:
    """Config 的替身：每次取属性都转给「当前账户」的那份配置。

    web 应用里有上百处闭包直接用 `cfg`；多租户形态下把它换成这个代理，闭包代码一行不改，
    读到的却总是正在处理的那个账户的配置与空间。"""

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(current_cfg(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(current_cfg(), name, value)

    def __repr__(self) -> str:
        return f"ConfigProxy(tenant={tenant_id()!r})"


def in_context(fn: Callable[[], Any]) -> Callable[[], Any]:
    """把当前上下文（账户、界面语言）带进新线程——threading.Thread 默认不继承 contextvar。"""
    ctx = contextvars.copy_context()
    return lambda: ctx.run(fn)


# ---------- 按账户的锁 ----------

_local_locks: dict[tuple[str, str], threading.RLock] = {}
_local_guard = threading.Lock()
_lock_backend: Any = None             # 多租户形态：数据库咨询锁（storage.pg.PgStore）


def set_lock_backend(backend: Any) -> None:
    global _lock_backend
    _lock_backend = backend


@contextmanager
def tenant_lock(name: str, blocking: bool = True) -> Iterator[bool]:
    """按「账户 + 名字」互斥。本机版是进程内可重入锁；多租户形态下多个实例可能同时处理同一账户，
    改为数据库咨询锁。yield 是否拿到锁（blocking=False 时可能为 False）。"""
    tid = tenant_id()
    if _lock_backend is not None:
        with _lock_backend.lock(tid, name, blocking=blocking) as got:
            yield got
        return
    with _local_guard:
        lk = _local_locks.setdefault((tid, name), threading.RLock())
    got = lk.acquire(blocking=blocking)
    try:
        yield got
    finally:
        if got:
            lk.release()
