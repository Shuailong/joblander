"""账户的开通、删除、导出、导入（含从 Fly 卷迁移）。

账户根的布局与 Fly 机器上的 /data 完全一致：<根>/config.yaml + <根>/workspace/…。
所以迁移就是把 Fly 卷打包原样搬进账户根，导出就是原样打包回去（回退、或给用户下载）。
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

from joblander.cloud import backend
from joblander.tenancy import use_tenant

SKIP_TOP = {"lost+found"}          # ext4 卷根目录自带，不是用户数据


def default_config(lang: str | None = None) -> dict[str, Any]:
    """与 deploy/entrypoint.sh 首次启动写的最小配置一致；真实的个人参数由网页设置向导写入。"""
    raw: dict[str, Any] = {
        "workspace_dir": "/data/workspace",
        "llm": {"provider": "openai",
                "model": os.environ.get("JOBLANDER_MODEL", "gpt-5.6-sol"),
                "model_flash": os.environ.get("JOBLANDER_MODEL_FLASH", "gpt-5.6-luna"),
                "model_eval": os.environ.get("JOBLANDER_MODEL_EVAL", "gpt-5.6-sol")},
        "sentinel": {"rules": []},
    }
    if lang in ("zh", "en"):
        raw["ui_lang"] = lang
    return raw


def provision(tenant_id: str, lang: str | None = None) -> dict[str, Any]:
    """开通账户（幂等）：建账户与数据密钥、写最小配置、搭 workspace 脚手架。"""
    from joblander.onboard import onboard
    s = backend.store()
    s.create_tenant(tenant_id)
    root = backend.tenant_root(tenant_id)
    (root / "workspace").mkdir(exist_ok=True)
    cp = root / "config.yaml"
    fresh = not cp.exists()
    if fresh:
        cp.write_text(yaml.safe_dump(default_config(lang), allow_unicode=True, sort_keys=False),
                      encoding="utf-8")
    t = backend.tenant(tenant_id)
    with use_tenant(t):
        onboard(t.cfg)
    return {"tenant": tenant_id, "created": fresh}


def delete(tenant_id: str) -> None:
    backend.store().delete_tenant(tenant_id)


def _files(root: Any) -> list[Any]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def manifest_tenant(tenant_id: str) -> dict[str, str]:
    """从账户空间读回每个文件（经解密）算 SHA-256：迁移后与源头清单逐个比对。"""
    root = backend.tenant_root(tenant_id)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in _files(root)}


def manifest_dir(path: str | Path) -> dict[str, str]:
    """源头（Fly 机器上的 /data）的清单，格式与 manifest_tenant 相同。"""
    base = Path(path)
    out = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if rel.parts and rel.parts[0] in SKIP_TOP:
            continue
        if p.is_file() and not p.is_symlink():
            out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def export_zip(tenant_id: str) -> bytes:
    """整个账户根打包（含原样的 config.yaml）。只给内部用：迁移回退、运营协助导出。
    用户自己的「导出全部数据」走引擎的 /api/export（会抹掉配置里的密钥）。"""
    root = backend.tenant_root(tenant_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in _files(root):
            z.writestr(p.relative_to(root).as_posix(), p.read_bytes())
    return buf.getvalue()


def import_tar(tenant_id: str, data: bytes) -> dict[str, Any]:
    """把 Fly 卷的打包（`tar czf - -C /data .`）原样搬进账户根，返回读回后的清单。

    只收普通文件与目录；符号链接、设备文件、越界路径一律跳过。
    导入结果与源头逐文件一致：不跑开通脚手架（Fly 机器首次启动时已经跑过），重跑时先清空
    旧副本再导入——切流前一天的预拷贝之后源头删掉的文件，不会残留在新账户里。"""
    s = backend.store()
    if s.has_tenant(tenant_id):
        s.delete_tenant(tenant_id)
    s.create_tenant(tenant_id)
    root = backend.tenant_root(tenant_id)
    written, skipped = 0, []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for m in tar.getmembers():
            name = m.name
            while name.startswith("./"):          # 只去掉 tar 的「./」前缀；.credentials 这类隐藏目录照留
                name = name[2:]
            rel = Path(name)
            parts = [x for x in rel.parts if x not in ("", ".")]
            if not parts:
                continue
            if parts[0] in SKIP_TOP or ".." in parts or rel.is_absolute():
                skipped.append(m.name)
                continue
            dst = root.joinpath(*parts)
            if m.isdir():
                dst.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                dst.parent.mkdir(parents=True, exist_ok=True)
                f = tar.extractfile(m)
                dst.write_bytes(f.read() if f else b"")
                written += 1
            else:
                skipped.append(m.name)
    return {"tenant": tenant_id, "files": written, "skipped": skipped,
            "manifest": manifest_tenant(tenant_id)}
