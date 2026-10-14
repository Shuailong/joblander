"""多租户形态端到端：真实的引擎应用跑在内存后端上，两个账户共享同一个进程。

验证：没有 / 伪造账户令牌一律 401；账户 A 的配置、文件、任务托盘、导出对 B 不可见；
任务服务按账户跑调度；Fly 卷打包导入后逐文件校验一致、导出原样还原。
"""

from __future__ import annotations

import io
import os
import tarfile
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from joblander import isolation, tasks, tenancy
from joblander.cloud import accounts, backend, tokens
from joblander.storage.memfs import MemoryStore

SECRET = "s" * 40
A, B = "tenant-aaaaaa", "tenant-bbbbbb"


@pytest.fixture
def multi(monkeypatch):
    monkeypatch.setenv("JOBLANDER_MODE", "multi")
    monkeypatch.setenv("JOBLANDER_STORE", "memory")
    monkeypatch.setenv("JOBLANDER_TENANT_TOKEN_SECRET", SECRET)
    monkeypatch.setenv("JOBLANDER_TASKS_SYNC", "1")
    monkeypatch.delenv("JOBLANDER_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("JOBLANDER_SANDBOX_URL", raising=False)
    backend.install(MemoryStore())
    accounts.provision(A, "zh")
    accounts.provision(B, "en")
    yield
    tenancy.set_lock_backend(None)
    tasks.set_table(tasks.MemoryTable())
    backend._store = None


def _engine():
    from joblander.cloud.engine import create_engine_app
    return TestClient(create_engine_app(), base_url="http://127.0.0.1")


def _h(tid: str) -> dict:
    return {"x-joblander-tenant-token": tokens.sign(tid)}


def test_tokens_roundtrip_and_reject_tampering():
    key = b"k" * 40
    tok = tokens.sign(A, key=key, now=1000)
    assert tokens.verify(tok, key=key, now=1100) == A
    with pytest.raises(tokens.TokenError):
        tokens.verify(tok, key=key, now=1000 + tokens.TTL + 1)            # 过期
    with pytest.raises(tokens.TokenError):
        tokens.verify(tok, key=b"x" * 40, now=1100)                      # 别的密钥
    with pytest.raises(tokens.TokenError):
        tokens.verify(tok, key=key, aud="internal", now=1100)            # 别的受众
    h, body, sig = tok.split(".")
    forged = tokens._b64(b'{"sub":"tenant-bbbbbb","aud":"engine","iat":1000,"exp":9999999999}')
    with pytest.raises(tokens.TokenError):
        tokens.verify(f"{h}.{forged}.{sig}", key=key, now=1100)          # 改了账户却没重签
    with pytest.raises(tokens.TokenError):
        tokens.sign("../etc", key=key)                                   # 账户 ID 格式


def test_requests_need_a_valid_tenant_token(multi):
    c = _engine()
    assert c.get("/healthz").status_code == 200
    assert c.get("/settings").status_code == 401
    before = isolation.counts().get("token", 0)
    assert c.get("/settings", headers={"x-joblander-tenant-token": "a.b.c"}).status_code == 401
    assert isolation.counts().get("token", 0) == before + 1               # 伪造令牌记一笔
    gone = tokens.sign("tenant-cccccc")
    assert c.get("/settings", headers={"x-joblander-tenant-token": gone}).status_code == 404
    assert c.get("/settings", headers=_h(A)).status_code == 200


def test_settings_and_files_stay_in_their_account(multi):
    c = _engine()
    assert c.post("/api/settings/lang", data={"lang": "en"}, headers=_h(A)).status_code == 200
    assert backend.tenant_config(A).raw["ui_lang"] == "en"
    assert backend.tenant_config(B).raw["ui_lang"] == "en"                # B 开通时就是 en，没被 A 影响
    c.post("/api/settings/lang", data={"lang": "zh"}, headers=_h(B))
    assert backend.tenant_config(A).raw["ui_lang"] == "en"
    assert backend.tenant_config(B).raw["ui_lang"] == "zh"

    secret = backend.tenant_root(A) / "workspace" / "03-materials" / "salary-floor.md"
    secret.write_text("A 的薪资底线：保密", encoding="utf-8")
    za = zipfile.ZipFile(io.BytesIO(c.get("/api/export", headers=_h(A)).content))
    zb = zipfile.ZipFile(io.BytesIO(c.get("/api/export", headers=_h(B)).content))
    assert "workspace/03-materials/salary-floor.md" in za.namelist()
    assert not any("salary-floor" in n for n in zb.namelist())
    r = c.get("/files/03-materials/salary-floor.md", headers=_h(B))
    assert r.status_code == 404


def test_task_tray_is_per_account(multi):
    with tenancy.use_tenant(backend.tenant(A)):
        tid = tasks.start("research", "尽调 · Acme", lambda: {"ok": 1})
    c = _engine()
    assert [t["id"] for t in c.get("/api/tasks", headers=_h(A)).json()] == [tid]
    assert c.get("/api/tasks", headers=_h(B)).json() == []
    c.post("/api/tasks/dismiss", data={"id": tid}, headers=_h(B))         # B 销不了 A 的单
    assert [t["id"] for t in c.get("/api/tasks", headers=_h(A)).json()] == [tid]


def test_worker_runs_one_tick_per_account(multi, monkeypatch):
    from joblander.cloud import worker
    ran = []
    monkeypatch.setattr("joblander.daemon.Daemon.tick", lambda self: ran.append(self.cfg.root._fs.tenant_id))
    out = worker.fanout()
    assert out == {"tenants": 2, "ran": 2} and sorted(ran) == [A, B]
    # 上一轮还没结束：同一账户这一轮直接跳过
    with tenancy.use_tenant(backend.tenant(A)):
        with tenancy.tenant_lock("daemon-tick"):
            import threading
            got = []
            t = threading.Thread(target=lambda: got.append(worker.run_tick(A)))
            t.start(); t.join(5)
    assert got == [False]


def test_tick_merges_state_without_clobbering_web_stamps(multi, monkeypatch):
    from joblander.daemon import merge_state, tick_once

    def job(self):
        merge_state(self.cfg, {"last.notion_pull": "web-wrote-this"})   # 网页在本轮进行中写入
        self.state["done.morning"] = "2026-10-13"
    monkeypatch.setattr("joblander.daemon.Daemon.tick", job)
    t = backend.tenant(A)
    with tenancy.use_tenant(t):
        assert tick_once(t.cfg)
    import json
    state = json.loads((t.cfg.workspace_dir / "08-events" / "daemon-state.json").read_text(encoding="utf-8"))
    assert state["last.notion_pull"] == "web-wrote-this" and state["done.morning"] == "2026-10-13"


def test_fly_volume_import_roundtrip(multi, tmp_path):
    src = tmp_path / "data"
    (src / "workspace" / ".credentials").mkdir(parents=True)
    (src / "workspace" / "08-events").mkdir()
    (src / "lost+found").mkdir()
    (src / "config.yaml").write_text("workspace_dir: /data/workspace\nui_lang: zh\n", encoding="utf-8")
    (src / "workspace" / ".credentials" / "gmail_token.json").write_text('{"refresh": "x"}')
    (src / "workspace" / "08-events" / "event-log.jsonl").write_text('{"kind": "a"}\n' * 3)
    (src / "workspace" / "resume.pdf").write_bytes(os.urandom(4096))
    os.symlink("/etc/passwd", src / "workspace" / "evil")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(src, arcname=".")
    out = accounts.import_tar("tenant-ffffff", buf.getvalue())
    assert out["manifest"] == accounts.manifest_dir(src)                  # 逐文件 SHA-256 一致
    assert "workspace/evil" not in out["manifest"] and not any("lost+found" in k for k in out["manifest"])
    cfg = backend.tenant_config("tenant-ffffff")
    assert cfg.raw["ui_lang"] == "zh" and (cfg.workspace_dir / ".credentials" / "gmail_token.json").exists()
    z = zipfile.ZipFile(io.BytesIO(accounts.export_zip("tenant-ffffff")))
    assert z.read("workspace/resume.pdf") == (src / "workspace" / "resume.pdf").read_bytes()


def test_drill_refuses_without_sandbox_in_multi(multi):
    from joblander.drill import run_drill
    out = run_drill("two-sum", "class Solution: pass")
    assert out["ok"] is False and "沙箱" in out["error"]


def test_delete_account_removes_everything(multi):
    root = backend.tenant_root(A)
    (root / "workspace" / "x.md").write_text("x")
    accounts.delete(A)
    assert not backend.store().has_tenant(A)
    c = _engine()
    assert c.get("/settings", headers=_h(A)).status_code == 404


def test_isolation_violation_on_cross_tenant_ciphertext():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from joblander.storage import crypto
    aead = AESGCM(AESGCM.generate_key(bit_length=256))
    blob = crypto.seal(aead, A, "file-1", b"secret")
    assert crypto.unseal(aead, A, "file-1", blob) == b"secret"
    before = isolation.counts().get("decrypt", 0)
    with pytest.raises(crypto.DecryptError):
        crypto.unseal(aead, B, "file-1", blob)                            # 搬到别的账户：解不开
    with pytest.raises(crypto.DecryptError):
        crypto.unseal(aead, A, "file-2", blob)                            # 搬到别的文件：解不开
    assert isolation.counts()["decrypt"] == before + 2
    kek = crypto.LocalKek(b"k" * 32)
    ring = crypto.Keyring(kek, ttl=0.01)
    wrapped = ring.new_wrapped_dek()
    a1 = ring.aead(A, lambda _: wrapped)
    time.sleep(0.02)
    a2 = ring.aead(A, lambda _: wrapped)
    assert a2.decrypt(blob[:12], a1.encrypt(blob[:12], b"z", b"ad"), b"ad") == b"z"   # 过期重解包，同一把钥


def test_engine_trusts_forwarded_host_only_with_valid_token(multi, monkeypatch):
    monkeypatch.setenv("JOBLANDER_ALLOWED_HOSTS", "app.test")
    c = TestClient(__import__("joblander.cloud.engine", fromlist=["x"]).create_engine_app(),
                   base_url="https://jl-engine-123.asia-southeast1.run.app")
    ok = c.get("/settings", headers={**_h(A), "x-forwarded-host": "app.test"})
    assert ok.status_code == 200                                     # 换回对外域名后过 Host 校验
    assert c.get("/settings", headers=_h(A)).status_code == 421       # 没有对外域名：内部 Host 不认
    assert c.get("/settings", headers={"x-forwarded-host": "app.test"}).status_code == 401   # 没令牌：免谈


def test_static_assets_go_through_account_context(multi, monkeypatch):
    """静态资源也经账户中间件：应用的中间件（界面语言、Host 校验）需要当前账户，绕过去会 500（staging 首次验收时页面无样式）。"""
    monkeypatch.setenv("JOBLANDER_ALLOWED_HOSTS", "app.test")
    c = TestClient(__import__("joblander.cloud.engine", fromlist=["x"]).create_engine_app(),
                   base_url="https://jl-engine-123.asia-southeast1.run.app")
    r = c.get("/static/app.css", headers={**_h(A), "x-forwarded-host": "app.test"})
    assert r.status_code == 200 and "text/css" in r.headers["content-type"]
    assert c.get("/static/app.css").status_code == 401
