"""账户空间的存储层。

本机 / Fly：workspace 就是本地文件夹，一切照旧用 pathlib.Path。
多租户：workspace 是 CloudPath（见 cloudpath.py），后端是 Postgres（pg.py）或内存（memfs.py）。

业务代码只需遵守三条，两种形态就都能跑：
1. 读写用 Path 的方法（path.open / read_text / write_bytes …），不要把路径交给内置 open()、os.*、shutil。
2. 需要「读全量→改→写全量」不留半截的，用 atomic_write_text。
3. 外部程序（Chromium、解析库）要真实文件时，用 local_copy / BytesIO，不要传路径字符串。
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from joblander.storage.cloudpath import CloudPath


def is_local(path: Any) -> bool:
    return isinstance(path, Path)


def atomic_write_text(path: Any, text: str) -> None:
    """要么旧内容，要么新内容，不会留下半截。本地：同目录临时文件 + os.replace；
    账户空间：后端每次写入本身就是一个事务。"""
    if not is_local(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def ws_path(cfg: Any, s: str | Path) -> Any:
    """网页表单回传的路径字符串 → 路径对象（本地是 Path；账户空间里只会落在本账户根下）。"""
    ws = cfg.workspace_dir
    if isinstance(ws, CloudPath):
        return s if isinstance(s, CloudPath) else ws.from_str(str(s))
    return Path(s)


def as_path(p: Any) -> Any:
    """接受路径对象或字符串：已经是路径（含 CloudPath）就原样返回。"""
    return Path(p) if isinstance(p, str) else p


def bytes_io(path: Any) -> io.BytesIO:
    """给只认文件对象的解析库（pypdf、zipfile）用。"""
    return io.BytesIO(path.read_bytes())


@contextmanager
def local_copy(path: Any) -> Iterator[Path]:
    """把账户空间里的文件临时落成本地文件（给 Chromium 之类只认文件路径的外部程序）。本地路径原样给出。"""
    if is_local(path):
        yield path
        return
    d = Path(tempfile.mkdtemp(prefix="jl-ws-"))
    try:
        p = d / (path.name or "file")
        p.write_bytes(path.read_bytes())
        yield p
    finally:
        shutil.rmtree(d, ignore_errors=True)
