"""CloudPath 与 pathlib.Path 行为一致：同一串操作分别跑在本地临时目录与账户空间（内存后端），
每一步的可观察结果（内容、列表、异常类型）必须相同。另测账户空间走不出自己的根、账户之间互不可见。"""

from __future__ import annotations

import pytest

from joblander.eventlog import EventLog
from joblander.storage.cloudpath import CloudPath
from joblander.storage.memfs import MemoryStore


def _cloud_root(tenant: str = "tenant-aaaaaa", store: MemoryStore | None = None) -> CloudPath:
    store = store or MemoryStore()
    store.create_tenant(tenant)
    return CloudPath(store.fs(tenant))


def _try(fn):
    try:
        return ("ok", fn())
    except Exception as e:                      # 比较异常类型，不比较消息
        return ("err", type(e).__name__)


def scenario(root) -> list:
    out = []
    ws = root / "workspace"
    out.append(_try(lambda: ws.mkdir()))
    out.append(_try(lambda: ws.mkdir()))                                  # FileExistsError
    out.append(_try(lambda: ws.mkdir(exist_ok=True)))
    out.append(_try(lambda: (ws / "a" / "b").mkdir()))                    # FileNotFoundError
    out.append(_try(lambda: (ws / "a" / "b").mkdir(parents=True)))
    f = ws / "a" / "note.md"
    out.append(_try(lambda: f.write_text("第一行\r\nsecond\n", encoding="utf-8")))
    out.append(_try(lambda: f.read_text(encoding="utf-8")))               # 通用换行：\r\n → \n
    out.append(_try(lambda: f.read_bytes()))
    with f.open("a", encoding="utf-8") as fh:
        fh.write("追加\n")
    out.append(_try(lambda: f.read_text(encoding="utf-8")))
    out.append(_try(lambda: f.stat().st_size))
    out.append(_try(lambda: (ws / "missing.txt").read_text()))            # FileNotFoundError
    out.append(_try(lambda: (ws / "nodir" / "x.txt").write_text("x")))    # FileNotFoundError
    out.append(_try(lambda: (ws / "a").read_text()))                      # IsADirectoryError
    (ws / "a" / "b" / "deep.md").write_text("deep", encoding="utf-8")
    (ws / "a" / "data.json").write_bytes(b'{"k": 1}')
    (ws / ".credentials").mkdir()
    (ws / ".credentials" / "tok.json").write_text("{}", encoding="utf-8")
    out.append(sorted(p.name for p in ws.iterdir()))
    out.append(sorted(p.relative_to(ws).as_posix() for p in ws.glob("a/*.json")))
    out.append(sorted(p.relative_to(ws).as_posix() for p in ws.glob("**/*.md")))
    out.append(sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()))
    out.append(sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_dir()))
    out.append((f.exists(), f.is_file(), f.is_dir(), (ws / "a").is_dir(), (ws / "zz").exists()))
    out.append((f.name, f.stem, f.suffix, f.with_suffix(".txt").name, f.parent.name))
    # 改名：文件、覆盖已有文件、整个目录
    g = f.rename(ws / "a" / "renamed.md")
    out.append((f.exists(), g.read_text(encoding="utf-8")))
    (ws / "a" / "other.md").write_text("other", encoding="utf-8")
    (ws / "a" / "other.md").replace(g)
    out.append(g.read_text(encoding="utf-8"))
    moved = (ws / "a" / "b").rename(ws / "moved")
    out.append(sorted(p.relative_to(ws).as_posix() for p in moved.rglob("*")))
    out.append((ws / "a" / "b").exists())
    out.append(_try(lambda: (ws / "a").rmdir()))                          # 非空：OSError
    out.append(_try(lambda: g.unlink()))
    out.append(_try(lambda: g.unlink()))                                  # FileNotFoundError
    out.append(_try(lambda: g.unlink(missing_ok=True)))
    out.append(_try(lambda: (ws / "a" / "data.json").open("x")))          # FileExistsError
    out.append(_try(lambda: ws.joinpath("a", "data.json").read_text()))
    return out


def test_cloudpath_matches_pathlib(tmp_path):
    local = scenario(tmp_path)
    cloud = scenario(_cloud_root())
    for i, (a, b) in enumerate(zip(local, cloud)):
        assert a == b, f"第 {i} 步不一致：本地 {a!r} ≠ 账户空间 {b!r}"
    assert len(local) == len(cloud)


def test_eventlog_on_both_backends(tmp_path):
    for root in (tmp_path, _cloud_root()):
        log = EventLog(root / "workspace" / "08-events" / "event-log.jsonl")
        for i in range(5):
            log.append("k", "test", {"i": i})
        assert [e["payload"]["i"] for e in log.tail(2)] == [3, 4]
        assert log.last("k")["payload"]["i"] == 4
        assert log.count() == 5


def test_cannot_escape_tenant_root():
    root = _cloud_root()
    ws = root / "workspace"
    ws.mkdir()
    assert (ws / "/etc/passwd").key == "etc/passwd"           # 绝对路径落在账户根下
    assert (ws / "../../../../x").resolve().key == "x"         # .. 夹在账户根
    p = ws / "a.txt"
    assert ws.from_str(str(p)) == p                            # 字符串往返（网页表单回传路径）
    assert str(p) == "/data/workspace/a.txt"


def test_tenants_cannot_see_each_other():
    store = MemoryStore()
    a = _cloud_root("tenant-aaaaaa", store)
    b = _cloud_root("tenant-bbbbbb", store)
    (a / "secret.txt").write_text("A 的薪资底线", encoding="utf-8")
    assert not (b / "secret.txt").exists()
    assert list(b.iterdir()) == []
    with pytest.raises(OSError):
        (a / "secret.txt").rename(b / "stolen.txt")            # 跨账户移动直接拒绝
    assert a / "secret.txt" != b / "secret.txt"
