"""CloudPath —— 与 pathlib.Path 兼容的「账户空间」路径。

引擎有约 300 处文件读写，全部以 `cfg.workspace_dir` 为根、用 pathlib 的方法。多租户形态下
workspace_dir 换成 CloudPath：同样的 `/`、read_text、write_text、glob、mkdir、rename……，
字节却落在按账户隔离的后端（Postgres + Cloud Storage，或测试用的内存后端）。

约定：
- 每个 CloudPath 绑定一个账户的后端（TenantFS），永远走不出这个账户的命名空间：
  拼上绝对路径或 `..` 也只会落在本账户根下。
- 字符串形式模拟 Fly 机器上的布局（根 = /data，空间 = /data/workspace），迁移前后
  数据里记下的绝对路径与事件里的 "out" 字段保持一致。
- 不实现 __fspath__：误把它交给 open()/os.* 会立刻报 TypeError，而不是悄悄写到本地磁盘。
"""

from __future__ import annotations

import fnmatch
import io
import re
import stat as stat_mod
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
from typing import Any, Iterator, Protocol

ROOT = "/data"


@dataclass(frozen=True)
class Entry:
    key: str                 # 相对账户根的 POSIX 路径，根为 ""
    is_dir: bool
    size: int = 0
    mtime_ns: int = 0


class TenantFS(Protocol):
    """一个账户的存储后端。key 已规范化（无前导斜杠、无 . 与 ..），根为 ""。

    语义对齐 POSIX：写文件要求父目录已存在；目录显式存在（mkdir 建出来）；
    rename 目标是文件时覆盖，目标是非空目录时报错。"""

    tenant_id: str

    def stat(self, key: str) -> Entry | None: ...
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes) -> None: ...
    def append(self, key: str, data: bytes) -> None: ...
    def mkdir(self, key: str) -> None: ...
    def rmdir(self, key: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def children(self, key: str) -> list[Entry]: ...
    def descendants(self, key: str) -> list[Entry]: ...
    def rename(self, src: str, dst: str) -> None: ...


@dataclass(frozen=True)
class CloudStat:
    st_size: int
    st_mtime_ns: int
    st_mode: int

    @property
    def st_mtime(self) -> float:
        return self.st_mtime_ns / 1e9

    st_ctime = st_mtime
    st_atime = st_mtime


def _norm(parts: tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if out:
                out.pop()
            continue                # 夹在账户根：.. 走不出去
        out.append(p)
    return tuple(out)


def _split(s: str) -> tuple[tuple[str, ...], bool]:
    """字符串 → (片段, 是否绝对)。/data/... 视为账户根下；其他绝对路径也落在账户根下。"""
    absolute = s.startswith("/")
    if absolute and (s == ROOT or s.startswith(ROOT + "/")):
        s = s[len(ROOT):]
    return tuple(x for x in s.split("/") if x), absolute


class CloudPath:
    __slots__ = ("_fs", "_parts")

    def __init__(self, fs: TenantFS, parts: tuple[str, ...] = ()):
        self._fs = fs
        self._parts = tuple(parts)

    # ---------- 构造与纯路径运算 ----------

    def _make(self, parts: tuple[str, ...]) -> "CloudPath":
        return CloudPath(self._fs, parts)

    def joinpath(self, *others: Any) -> "CloudPath":
        parts = self._parts
        for o in others:
            if isinstance(o, CloudPath):
                parts = o._parts
                continue
            segs, absolute = _split(str(o) if isinstance(o, PurePath) else o)
            parts = segs if absolute else parts + segs
        return self._make(parts)

    __truediv__ = joinpath

    def from_str(self, s: str) -> "CloudPath":
        """把 str(CloudPath) 或相对账户根的字符串还原成路径（网页表单回传路径时用）。"""
        prefix = getattr(self._fs, "local_prefix", "")      # 仅测试用的本地目录后端会设
        if prefix and (s == prefix or s.startswith(prefix + "/")):
            s = s[len(prefix):]
        segs, _ = _split(s)
        return self._make(segs)

    @property
    def key(self) -> str:
        return "/".join(_norm(self._parts))

    @property
    def name(self) -> str:
        return self._parts[-1] if self._parts else ""

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix if self._parts else ""

    @property
    def suffixes(self) -> list[str]:
        return PurePosixPath(self.name).suffixes if self._parts else []

    @property
    def stem(self) -> str:
        return PurePosixPath(self.name).stem if self._parts else ""

    @property
    def parent(self) -> "CloudPath":
        return self._make(self._parts[:-1]) if self._parts else self

    @property
    def parents(self) -> tuple["CloudPath", ...]:
        return tuple(self._make(self._parts[:i]) for i in range(len(self._parts) - 1, -1, -1))

    @property
    def parts(self) -> tuple[str, ...]:
        return ("/", *PurePosixPath(ROOT).parts[1:], *self._parts)

    def with_name(self, name: str) -> "CloudPath":
        if not self._parts:
            raise ValueError(f"{self!r} has an empty name")
        return self._make(self._parts[:-1] + (name,))

    def with_suffix(self, suffix: str) -> "CloudPath":
        return self.with_name(str(PurePosixPath(self.name).with_suffix(suffix)))

    def with_stem(self, stem: str) -> "CloudPath":
        return self.with_name(stem + self.suffix)

    def relative_to(self, other: Any) -> PurePosixPath:
        base = other._parts if isinstance(other, CloudPath) else _split(str(other))[0]
        mine = _norm(self._parts)
        base = _norm(base)
        if mine[:len(base)] != base:
            raise ValueError(f"{self} is not in the subpath of {other}")
        return PurePosixPath(*mine[len(base):]) if mine[len(base):] else PurePosixPath(".")

    def is_relative_to(self, other: Any) -> bool:
        try:
            self.relative_to(other)
            return True
        except ValueError:
            return False

    def resolve(self, strict: bool = False) -> "CloudPath":
        p = self._make(_norm(self._parts))
        if strict and not p.exists():
            raise FileNotFoundError(str(p))
        return p

    def absolute(self) -> "CloudPath":
        return self

    def expanduser(self) -> "CloudPath":
        return self

    def as_posix(self) -> str:
        return str(self)

    def match(self, pattern: str) -> bool:
        return PurePosixPath(str(self)).match(pattern)

    def __str__(self) -> str:
        return ROOT + ("/" + "/".join(self._parts) if self._parts else "")

    def __repr__(self) -> str:
        return f"CloudPath({str(self)!r})"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, CloudPath) and other._fs.tenant_id == self._fs.tenant_id
                and _norm(other._parts) == _norm(self._parts))

    def __hash__(self) -> int:
        return hash((self._fs.tenant_id, _norm(self._parts)))

    def __lt__(self, other: "CloudPath") -> bool:
        return self._parts < other._parts

    def __le__(self, other: "CloudPath") -> bool:
        return self._parts <= other._parts

    def __gt__(self, other: "CloudPath") -> bool:
        return self._parts > other._parts

    def __ge__(self, other: "CloudPath") -> bool:
        return self._parts >= other._parts

    # ---------- 查询 ----------

    def _entry(self) -> Entry | None:
        return self._fs.stat(self.key)

    def exists(self) -> bool:
        return self._entry() is not None

    def is_file(self) -> bool:
        e = self._entry()
        return e is not None and not e.is_dir

    def is_dir(self) -> bool:
        e = self._entry()
        return e is not None and e.is_dir

    def is_symlink(self) -> bool:
        return False

    def is_absolute(self) -> bool:
        return True

    def lstat(self) -> CloudStat:
        return self.stat()

    def stat(self) -> CloudStat:
        e = self._entry()
        if e is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        mode = (stat_mod.S_IFDIR | 0o755) if e.is_dir else (stat_mod.S_IFREG | 0o644)
        return CloudStat(st_size=e.size, st_mtime_ns=e.mtime_ns, st_mode=mode)

    def iterdir(self) -> Iterator["CloudPath"]:
        e = self._entry()
        if e is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if not e.is_dir:
            raise NotADirectoryError(20, "Not a directory", str(self))
        base = _norm(self._parts)
        for c in self._fs.children(self.key):
            yield self._make(base + (c.key.rsplit("/", 1)[-1],))

    def glob(self, pattern: str) -> Iterator["CloudPath"]:
        """pathlib 语义：* 只匹配一段内的字符（不跨 /，默认不匹配以 . 开头的名字？pathlib 会匹配，
        这里同样匹配）；** 匹配任意层目录（含零层）。"""
        if not self.is_dir():
            return iter(())
        segs = [s for s in pattern.split("/") if s]
        if not segs:
            return iter(())
        base = _norm(self._parts)
        entries = self._fs.descendants(self.key)
        rel_entries = []
        for e in entries:
            rel = tuple(e.key.split("/"))[len(base):] if self.key else tuple(e.key.split("/"))
            rel_entries.append((rel, e))
        out = []
        for rel, e in rel_entries:
            if _glob_match(segs, list(rel)):
                out.append(self._make(base + rel))
        if segs[-1] == "**":               # pathlib：以 ** 结尾只返回目录（含自身）
            out = [p for p in out if p.is_dir()] + [self]
        return iter(out)

    def rglob(self, pattern: str) -> Iterator["CloudPath"]:
        return self.glob("**/" + pattern)

    # ---------- 读写 ----------

    def read_bytes(self) -> bytes:
        e = self._entry()
        if e is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if e.is_dir:
            raise IsADirectoryError(21, "Is a directory", str(self))
        return self._fs.read(self.key)

    def read_text(self, encoding: str | None = None, errors: str | None = None,
                  newline: str | None = None) -> str:
        with self.open("r", encoding=encoding, errors=errors, newline=newline) as f:
            return f.read()

    def _check_writable(self) -> None:
        if not self._parts:
            raise IsADirectoryError(21, "Is a directory", str(self))
        parent = self._fs.stat(self.parent.key)
        if parent is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if not parent.is_dir:
            raise NotADirectoryError(20, "Not a directory", str(self))
        e = self._entry()
        if e is not None and e.is_dir:
            raise IsADirectoryError(21, "Is a directory", str(self))

    def write_bytes(self, data: bytes) -> int:
        self._check_writable()
        data = bytes(data)
        self._fs.write(self.key, data)
        return len(data)

    def write_text(self, data: str, encoding: str | None = None, errors: str | None = None,
                   newline: str | None = None) -> int:
        if not isinstance(data, str):
            raise TypeError(f"data must be str, not {type(data).__name__}")
        with self.open("w", encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    def open(self, mode: str = "r", buffering: int = -1, encoding: str | None = None,
             errors: str | None = None, newline: str | None = None):
        if "+" in mode:
            raise ValueError(f"CloudPath 不支持读写混合模式：{mode}")
        binary = "b" in mode
        kind = mode.replace("b", "").replace("t", "")
        if kind == "r":
            raw = io.BytesIO(self.read_bytes())
            if binary:
                return raw
            return io.TextIOWrapper(raw, encoding=encoding or "utf-8", errors=errors, newline=newline)
        if kind in ("w", "x", "a"):
            self._check_writable()
            if kind == "x" and self.exists():
                raise FileExistsError(17, "File exists", str(self))
            sink = _Sink(self._fs, self.key, append=(kind == "a"))
            if binary:
                return sink
            return io.TextIOWrapper(sink, encoding=encoding or "utf-8", errors=errors, newline=newline,
                                    write_through=True)
        raise ValueError(f"invalid mode: {mode!r}")

    # ---------- 目录与移动 ----------

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if not self._parts:
            if not exist_ok:
                raise FileExistsError(17, "File exists", str(self))
            return
        e = self._entry()
        if e is not None:
            if e.is_dir and exist_ok:
                return
            raise FileExistsError(17, "File exists", str(self))
        parent = self._fs.stat(self.parent.key)
        if parent is None:
            if not parents:
                raise FileNotFoundError(2, "No such file or directory", str(self))
            self.parent.mkdir(parents=True, exist_ok=True)
        elif not parent.is_dir:
            raise NotADirectoryError(20, "Not a directory", str(self))
        self._fs.mkdir(self.key)

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        e = self._entry()
        if e is not None:
            if not exist_ok:
                raise FileExistsError(17, "File exists", str(self))
            if not e.is_dir:
                self._fs.append(self.key, b"")      # 只刷新修改时间
            return
        self.write_bytes(b"")

    def unlink(self, missing_ok: bool = False) -> None:
        e = self._entry()
        if e is None:
            if missing_ok:
                return
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if e.is_dir:
            raise IsADirectoryError(21, "Is a directory", str(self))
        self._fs.delete(self.key)

    def rmdir(self) -> None:
        e = self._entry()
        if e is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if not e.is_dir:
            raise NotADirectoryError(20, "Not a directory", str(self))
        if self._fs.children(self.key):
            raise OSError(66, "Directory not empty", str(self))
        self._fs.rmdir(self.key)

    def rename(self, target: Any) -> "CloudPath":
        # pathlib 把相对字符串目标解释为相对当前目录；账户空间里没有当前目录，按账户根解释
        dst = target if isinstance(target, CloudPath) else CloudPath(self._fs).joinpath(target)
        if dst._fs.tenant_id != self._fs.tenant_id:
            raise OSError(18, "Cross-tenant rename", str(dst))
        src_e = self._entry()
        if src_e is None:
            raise FileNotFoundError(2, "No such file or directory", str(self))
        if dst.key == self.key:
            return dst
        if src_e.is_dir and (dst.key + "/").startswith(self.key + "/"):
            raise OSError(22, "Invalid argument", str(dst))
        dst_parent = self._fs.stat(dst.parent.key)
        if dst_parent is None or not dst_parent.is_dir:
            raise FileNotFoundError(2, "No such file or directory", str(dst))
        dst_e = dst._entry()
        if dst_e is not None:
            if src_e.is_dir and not dst_e.is_dir:
                raise NotADirectoryError(20, "Not a directory", str(dst))
            if not src_e.is_dir and dst_e.is_dir:
                raise IsADirectoryError(21, "Is a directory", str(dst))
            if dst_e.is_dir and self._fs.children(dst.key):
                raise OSError(66, "Directory not empty", str(dst))
        self._fs.rename(self.key, dst.key)
        return dst

    replace = rename

    def chmod(self, mode: int) -> None:
        """权限位在账户空间里没有意义（数据本身按账户加密），保持接口兼容。"""
        if not self.exists():
            raise FileNotFoundError(2, "No such file or directory", str(self))


def _glob_match(segs: list[str], rel: list[str]) -> bool:
    if not segs:
        return not rel
    head = segs[0]
    if head == "**":
        return any(_glob_match(segs[1:], rel[i:]) for i in range(len(rel) + 1))
    if not rel:
        return False
    return _seg_match(head, rel[0]) and _glob_match(segs[1:], rel[1:])


def _seg_match(pattern: str, name: str) -> bool:
    return re.fullmatch(fnmatch.translate(pattern), name) is not None


class _Sink(io.RawIOBase):
    """写入缓冲：close 时一次性提交（w）或追加（a）。"""

    def __init__(self, fs: TenantFS, key: str, append: bool):
        super().__init__()
        self._fs, self._key, self._append = fs, key, append
        self._buf = bytearray()
        self._committed = False

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:
        self._buf += bytes(b)
        return len(b)

    def close(self) -> None:
        if not self._committed and not self.closed:
            self._committed = True
            if self._append:
                self._fs.append(self._key, bytes(self._buf))
            else:
                self._fs.write(self._key, bytes(self._buf))
        super().close()
