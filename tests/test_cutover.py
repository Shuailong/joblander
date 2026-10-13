"""切流：Fly 卷在机器上打包（deploy/gcp/cutover.py 的远端脚本）→ 本机核对 → GCP 导入作业逐文件比对。

远端脚本在本机对一个假的 /data 目录跑（不冻结进程），产出的字节流与真实 ssh 传回的格式一致。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from joblander import tasks, tenancy
from joblander.cloud import accounts, backend
from joblander.cloud import cutover as job
from joblander.storage.memfs import MemoryStore

TOOL = Path(__file__).resolve().parents[1] / "deploy" / "gcp" / "cutover.py"


def _tool():
    spec = importlib.util.spec_from_file_location("cutover_tool", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def multi(monkeypatch):
    monkeypatch.setenv("JOBLANDER_MODE", "multi")
    monkeypatch.setenv("JOBLANDER_STORE", "memory")
    backend.install(MemoryStore())
    yield
    tenancy.set_lock_backend(None)
    tasks.set_table(tasks.MemoryTable())
    backend._store = None


def _fake_volume(root: Path) -> None:
    (root / "workspace" / "companies" / "acme").mkdir(parents=True)
    (root / "workspace" / "empty-dir").mkdir()
    (root / "lost+found").mkdir()
    (root / "lost+found" / "junk").write_text("x")
    (root / "config.yaml").write_text("workspace_dir: /data/workspace\nui_lang: zh\n", encoding="utf-8")
    (root / "workspace" / "companies" / "acme" / "notes.md").write_text("面试笔记\n", encoding="utf-8")
    (root / "workspace" / "resume.pdf").write_bytes(os.urandom(300_000))
    (root / "workspace" / ".credentials").mkdir()
    (root / "workspace" / ".credentials" / "notion.json").write_text('{"token": "secret"}')
    (root / "workspace" / "link").symlink_to(root / "config.yaml")


def _remote_export(tool, root: Path) -> bytes:
    """照 ssh 那样跑远端脚本：python3 -c '<压缩后的脚本>' <根目录> nofreeze，前后夹点 flyctl 的提示行。"""
    cmd = tool.python_c(tool.REMOTE_EXPORT, str(root), "nofreeze")
    out = subprocess.run(["sh", "-c", cmd.replace("python3 ", f"{sys.executable} ", 1)], capture_output=True,
                         check=True).stdout
    return b"Connecting to fdaa::3... complete\r\n" + out.replace(b"\n", b"\r\n")


def test_remote_export_stream_roundtrip(tmp_path):
    tool = _tool()
    _fake_volume(tmp_path / "data")
    head, blob = tool.parse_stream(_remote_export(tool, tmp_path / "data"))
    assert head["pids"] == [] and tool.manifest_of_tar(blob) == head["manifest"]
    assert set(head["manifest"]) == {"config.yaml", "workspace/companies/acme/notes.md", "workspace/resume.pdf",
                                     "workspace/.credentials/notion.json"}       # 不带 lost+found 与符号链接
    assert head["manifest"]["workspace/resume.pdf"] == hashlib.sha256(
        (tmp_path / "data" / "workspace" / "resume.pdf").read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="找不到"):
        tool.parse_stream(b"JLEXPORT {}\nAAAA")                                     # 半截断掉


def test_exported_volume_imports_and_verifies(multi, tmp_path):
    tool = _tool()
    _fake_volume(tmp_path / "data")
    head, blob = tool.parse_stream(_remote_export(tool, tmp_path / "data"))
    tid = "t0123456789abcdef0123"
    bucket = {"plan.json": json.dumps({"users": [{"email": "a@x.com", "tenant_id": tid},
                                                 {"email": "n@x.com", "tenant_id": None}]}).encode(),
              f"users/{tid}.tar.gz": blob, f"users/{tid}.manifest.json": json.dumps(head["manifest"]).encode()}
    rep = job.run("gs://b/cutover/x", store=bucket)
    assert rep["summary"] == {**rep["summary"], "planned": 1, "ok": 1}
    assert json.loads(bucket["report.json"])["tenants"][tid]["ok"]
    root = backend.tenant_root(tid)
    assert (root / "workspace" / "companies" / "acme" / "notes.md").read_text(encoding="utf-8") == "面试笔记\n"
    assert (root / "workspace" / "empty-dir").is_dir()                               # 空目录也搬过来
    assert accounts.manifest_tenant(tid) == head["manifest"]
    # 清单对不上（比如打包后源头又改了）：报告标红，网关库复制会拒绝
    bad = dict(head["manifest"], **{"config.yaml": "0" * 64})
    bucket[f"users/{tid}.manifest.json"] = json.dumps(bad).encode()
    rep = job.run("gs://b/cutover/x", only=[tid], store=bucket)
    assert not rep["tenants"][tid]["ok"] and rep["tenants"][tid]["diff"] == {"changed": ["config.yaml"]}
    # 彩排之后删了账户：plan 里列为作废，导入时把 GCP 上的副本删掉；别的账户（比如切流后新开的）不动
    accounts.provision("tlive000000000000000a")
    plan = json.loads(bucket["plan.json"])
    bucket["plan.json"] = json.dumps({"users": [plan["users"][1]], "retired": [tid]}).encode()
    rep = job.run("gs://b/cutover/x", store=bucket)
    assert rep["retired"] == [tid] and not backend.store().has_tenant(tid)
    assert backend.store().has_tenant("tlive000000000000000a")


def test_plan_keeps_tenant_ids_across_reruns(tmp_path):
    import sqlite3
    tool = _tool()
    db = sqlite3.connect(tmp_path / "gw.sqlite")
    db.execute("CREATE TABLE users (email TEXT, status TEXT, machine_id TEXT, volume_id TEXT)")
    db.executemany("INSERT INTO users VALUES (?,?,?,?)", [("a@x.com", "ready", "m1", "vol1"),
                                                          ("n@x.com", "new", None, None)])
    db.commit()
    first = tool.make_plan(tmp_path)
    db.execute("INSERT INTO users VALUES ('b@x.com', 'ready', 'm2', 'vol2')")
    db.commit()
    second = tool.make_plan(tmp_path)
    ids = {u["email"]: u["tenant_id"] for u in second["users"]}
    assert ids["a@x.com"] == {u["email"]: u["tenant_id"] for u in first["users"]}["a@x.com"]
    assert second["retired"] == []
    db.execute("DELETE FROM users WHERE email='a@x.com'")                       # 彩排后删了账户
    db.commit()
    third = tool.make_plan(tmp_path)
    assert third["retired"] == [ids["a@x.com"]]
    assert tool.make_plan(tmp_path)["retired"] == [ids["a@x.com"]]               # 再跑一次也不丢
    assert ids["n@x.com"] is None and ids["b@x.com"] and ids["b@x.com"] != ids["a@x.com"]
    from joblander.cloud.tokens import TENANT_RE
    assert all(TENANT_RE.match(i) for i in ids.values() if i)
