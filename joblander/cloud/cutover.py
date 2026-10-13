"""切流：把 Fly 卷的打包导入引擎账户。在 GCP 里以 Cloud Run 作业跑（引擎镜像，JOBLANDER_ROLE=cutover）：

  python -m joblander.cloud.cutover gs://<迁移桶>/cutover/<批次> [--only <账户号>…] [--jobs 2]

批次目录由运营者本机的 deploy/gcp/cutover.py 上传：plan.json、users/<账户号>.tar.gz、
users/<账户号>.manifest.json（在 Fly 机器上冻结引擎后打包、当场逐文件算的 SHA-256）。

每个账户：清空重导（可以反复跑，彩排与正式切流用同一批账户号）→ 从库里读回（经解密）逐文件比对清单。
结果合并进批次目录的 report.json；有任何账户对不上就以非零退出。网关库的复制（gw.cutover）只认全绿的报告。
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from joblander.cloud import accounts, backend


def compare(src: dict[str, str], dst: dict[str, str]) -> dict[str, list[str]]:
    return {"missing": sorted(set(src) - set(dst)), "extra": sorted(set(dst) - set(src)),
            "changed": sorted(k for k in set(src) & set(dst) if src[k] != dst[k])}


def import_one(get, tenant_id: str) -> dict[str, Any]:
    t0 = time.time()
    try:
        data = get(f"users/{tenant_id}.tar.gz")
        want = json.loads(get(f"users/{tenant_id}.manifest.json"))
        got = accounts.import_tar(tenant_id, data)
        diff = compare(want, got["manifest"])
        ok = not any(diff.values())
        out: dict[str, Any] = {"ok": ok, "files": got["files"], "bytes": len(data),
                               "seconds": round(time.time() - t0, 1)}
        if not ok:
            out["error"] = "；".join(f"{k} {len(v)} 个" for k, v in diff.items() if v)
            out["diff"] = {k: v[:20] for k, v in diff.items() if v}
        if got["skipped"]:
            out["skipped"] = got["skipped"][:20]
        return out
    except Exception as e:                                   # noqa: BLE001  记进报告，别的账户照跑
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:500], "seconds": round(time.time() - t0, 1)}


def run(batch: str, only: list[str] | None = None, jobs: int = 2, store=None) -> dict[str, Any]:
    """batch 是 gs://桶/目录；store 给测试用（{相对路径: bytes} 的字典，代替存储桶）。"""
    if store is None:
        from joblander import gcp
        bucket, _, prefix = batch.removeprefix("gs://").partition("/")
        prefix = prefix.strip("/")

        def get(name: str) -> bytes:
            return gcp.gcs_download(bucket, f"{prefix}/{name}")

        def put(name: str, data: bytes) -> None:
            gcp.gcs_upload(bucket, f"{prefix}/{name}", data)
    else:
        def get(name: str) -> bytes:
            return store[name]

        def put(name: str, data: bytes) -> None:
            store[name] = data
    plan = json.loads(get("plan.json"))
    ids = [u["tenant_id"] for u in plan["users"] if u.get("tenant_id")]
    if only:
        unknown = set(only) - set(ids)
        if unknown:
            raise SystemExit(f"plan 里没有这些账户：{sorted(unknown)}")
        ids = [i for i in ids if i in only]
    try:
        report = json.loads(get("report.json"))
    except Exception:                                        # noqa: BLE001  第一次跑：还没有报告
        report = {"tenants": {}}
    emails = {u["tenant_id"]: u["email"] for u in plan["users"] if u.get("tenant_id")}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for tid, res in zip(ids, pool.map(lambda i: import_one(get, i), ids)):
            report["tenants"][tid] = {"email": emails[tid], "at": time.time(), **res}
            print(json.dumps({"tenant": tid, **{k: v for k, v in res.items() if k != "diff"}}, ensure_ascii=False),
                  flush=True)
    if not only:                                             # 彩排之后删掉 / 重置了的账户：GCP 上的旧副本删掉
        gone = [t for t in plan.get("retired", []) if backend.store().has_tenant(t)]
        for t in gone:
            accounts.delete(t)
        report["retired"] = sorted(set(report.get("retired", [])) | set(gone))
    planned = set(emails)
    report["summary"] = {"planned": len(planned),
                         "ok": sum(1 for t in planned if report["tenants"].get(t, {}).get("ok")),
                         "at": time.time()}
    put("report.json", json.dumps(report, ensure_ascii=False, indent=1).encode())
    return report


def main(argv: list[str]) -> None:
    import argparse
    import os
    os.environ.setdefault("JOBLANDER_MODE", "multi")
    ap = argparse.ArgumentParser(prog="joblander.cloud.cutover")
    ap.add_argument("batch")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args(argv)
    backend.store()
    report = run(a.batch, a.only, a.jobs)
    s = report["summary"]
    print(json.dumps({"summary": s}, ensure_ascii=False))
    if s["ok"] != s["planned"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
