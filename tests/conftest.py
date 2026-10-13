"""可选的「账户空间」测试模式：JOBLANDER_TEST_CLOUDPATH=1 pytest

把每份测试配置的 workspace 换成 CloudPath，后端仍是同一个本地目录（LocalDirFS）。
测试准备数据照旧往 tmp_path 里写，引擎代码却只能经 CloudPath 的接口读写——
哪里绕过了它（交给内置 open()、os.*、外部程序），这里就会报 TypeError。
用来持续保证引擎代码对两种存储都成立；默认不开，不影响平时跑测试。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from joblander.storage.cloudpath import Entry


class LocalDirFS:
    """TenantFS 的本地目录实现：只在这个测试模式里用。"""

    def __init__(self, base: Path):
        self.base = base
        self.tenant_id = f"dir:{base}"
        self.local_prefix = str(base)          # 测试直接用本地绝对路径回传提案时也能认出来

    def _p(self, key: str) -> Path:
        return self.base / key if key else self.base

    def stat(self, key: str) -> Entry | None:
        p = self._p(key)
        try:
            st = p.stat()
        except OSError:
            return None
        return Entry(key, p.is_dir(), 0 if p.is_dir() else st.st_size, st.st_mtime_ns)

    def read(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def write(self, key: str, data: bytes) -> None:
        self._p(key).write_bytes(data)

    def append(self, key: str, data: bytes) -> None:
        with self._p(key).open("ab") as f:
            f.write(data)
        os.utime(self._p(key), ns=(time.time_ns(), time.time_ns()))

    def mkdir(self, key: str) -> None:
        self._p(key).mkdir()

    def rmdir(self, key: str) -> None:
        self._p(key).rmdir()

    def delete(self, key: str) -> None:
        self._p(key).unlink()

    def _entries(self, paths) -> list[Entry]:
        out = []
        for p in sorted(paths):
            if p.is_symlink():
                continue
            key = p.relative_to(self.base).as_posix()
            out.append(Entry(key, p.is_dir(), 0 if p.is_dir() else p.stat().st_size, p.stat().st_mtime_ns))
        return out

    def children(self, key: str) -> list[Entry]:
        return self._entries(self._p(key).iterdir())

    def descendants(self, key: str) -> list[Entry]:
        return self._entries(self._p(key).rglob("*"))

    def rename(self, src: str, dst: str) -> None:
        os.replace(self._p(src), self._p(dst))


@pytest.fixture(autouse=True)
def _workspace_as_cloudpath(monkeypatch):
    if not os.environ.get("JOBLANDER_TEST_CLOUDPATH"):
        yield
        return
    from joblander.config import Config, ConfigError
    from joblander.storage.cloudpath import CloudPath

    def workspace_dir(self):
        if self.root is not None:
            return self.root / "workspace"
        d = self.raw.get("workspace_dir")
        if not d:
            raise ConfigError("config 缺少 workspace_dir")
        base = Path(d)
        base.mkdir(parents=True, exist_ok=True)
        return CloudPath(LocalDirFS(base))

    monkeypatch.setattr(Config, "workspace_dir", property(workspace_dir))
    yield
