#!/usr/bin/env python3
"""切流工具：Fly → GCP。运营者本机跑，需要 flyctl 与 gcloud 都已登录。完整步骤见 cloud/gateway/OPERATIONS.gcp.md「切流」。

  cutover.py gw-backup   --dir D                      Fly 网关库 → D/gw.sqlite（sqlite 在线备份，一致）
  cutover.py plan        --dir D                      谁要搬、各自的新账户号 → D/plan.json（重跑保留已分配的账户号）
  cutover.py export      --dir D [--only 邮箱…] [--jobs 4] [--keep-running]
                                                      逐台：启动 → 冻结引擎进程 → 打包 /data 并逐文件算 SHA-256 → 解冻
                                                      → 停机；本机核对后存 D/users/<账户号>.tar.gz 与 .manifest.json
  cutover.py upload      --dir D --batch B            D → gs://<项目>-migration/cutover/B/
  cutover.py import      --batch B [--only 账户号…]    跑 GCP 上的导入作业（清空重导 + 逐文件比对），打印报告
  cutover.py gateway     --batch B [--force]          跑网关库复制作业（导入报告必须全绿）
  cutover.py maintenance on|off|status [说明…] --where fly|gcp

公共参数：--env prod|staging（默认 prod；项目默认 jl-<env>，用 --project 改）、--region、--dry-run（只打印命令）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import secrets
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FLY_GW_APP = "joblander-gw"
FLY_USERS_APP = "joblander-users"
DRY = False

# 在 Fly 用户机器上跑（python3 -c，参数：卷根目录、freeze|nofreeze）。冻结引擎（SIGSTOP）期间打包，
# 当场逐文件算 SHA-256，解冻后把 tar.gz 以 base64 打到标准输出（夹在 JLEXPORT 头与 JLEND 之间）。
REMOTE_EXPORT = r'''
import base64, hashlib, io, json, os, signal, sys, tarfile, tempfile, time
root = sys.argv[1] if len(sys.argv) > 1 else "/data"
freeze = (sys.argv[2] if len(sys.argv) > 2 else "freeze") == "freeze"
pids = []
if freeze:
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == os.getpid():
            continue
        try:
            argv = open("/proc/%s/cmdline" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        if b"web" in argv and any(a == b"joblander" or a.endswith(b"/joblander") for a in argv):
            pids.append(int(d))
    for p in pids:
        os.kill(p, signal.SIGSTOP)
manifest = {}
tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
try:
    if pids:
        time.sleep(1)
    with tarfile.open(fileobj=tmp, mode="w:gz", compresslevel=6) as tar:
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            if rel == ".":
                dirnames[:] = sorted(d for d in dirnames if d != "lost+found")
            else:
                dirnames.sort()
                tar.add(dirpath, arcname="./" + rel, recursive=False)
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                arc = os.path.normpath(os.path.join(rel, fn))
                with open(full, "rb") as f:
                    data = f.read()
                manifest[arc] = hashlib.sha256(data).hexdigest()
                ti = tar.gettarinfo(full, arcname="./" + arc)
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
finally:
    for p in pids:
        os.kill(p, signal.SIGCONT)
    tmp.close()
h = hashlib.sha256()
with open(tmp.name, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
head = {"pids": pids, "files": len(manifest), "bytes": os.path.getsize(tmp.name), "sha256": h.hexdigest(),
        "manifest": manifest}
out = sys.stdout.buffer
out.write(b"JLEXPORT " + json.dumps(head).encode() + b"\n")
with open(tmp.name, "rb") as f:
    base64.encode(f, out)
out.write(b"JLEND\n")
out.flush()
os.unlink(tmp.name)
'''

# 在 Fly 网关机器上跑：sqlite 在线备份（网关照常运行也一致），同样夹在 JLEXPORT / JLEND 之间传回
REMOTE_GW_BACKUP = r'''
import base64, hashlib, json, os, sqlite3, sys
src = sqlite3.connect(os.environ.get("GW_DB", "/data/gw.sqlite"))
dst = sqlite3.connect("/tmp/jl-gw-backup.sqlite")
src.backup(dst)
dst.close()
src.close()
data = open("/tmp/jl-gw-backup.sqlite", "rb").read()
out = sys.stdout.buffer
out.write(b"JLEXPORT " + json.dumps({"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}).encode() + b"\n")
out.write(base64.encodebytes(data))
out.write(b"JLEND\n")
out.flush()
os.unlink("/tmp/jl-gw-backup.sqlite")
'''


def python_c(code: str, *args: str) -> str:
    """把一段脚本压成 python3 -c 的单引号参数（脚本里不能出现单引号，所以整段 base64）。"""
    packed = base64.b64encode(zlib.compress(code.encode(), 9)).decode()
    tail = " ".join(shlex.quote(a) for a in args)
    return f"python3 -c 'import base64,zlib;exec(zlib.decompress(base64.b64decode(\"{packed}\")))' {tail}".strip()


def parse_stream(raw: bytes) -> tuple[dict, bytes]:
    """从 ssh 的标准输出里取出 JLEXPORT 头与 base64 正文（前后可能夹着 flyctl 自己的提示行）。"""
    lines = raw.replace(b"\r", b"").split(b"\n")
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith(b"JLEXPORT "))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == b"JLEND")
    except StopIteration:
        tail = raw[-500:].decode(errors="replace")
        raise RuntimeError(f"输出里找不到完整的导出（可能中途断了）：…{tail}") from None
    head = json.loads(lines[start][len(b"JLEXPORT "):])
    blob = base64.b64decode(b"".join(lines[start + 1:end]))
    if len(blob) != head["bytes"] or hashlib.sha256(blob).hexdigest() != head["sha256"]:
        raise RuntimeError("传回的数据与远端的校验和对不上")
    return head, blob


def manifest_of_tar(blob: bytes) -> dict[str, str]:
    out = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile():
                name = m.name
                while name.startswith("./"):
                    name = name[2:]
                f = tar.extractfile(m)
                out[name] = hashlib.sha256(f.read() if f else b"").hexdigest()
    return out


# ---------- 命令行工具封装 ----------

def sh(cmd: list[str], *, timeout: float = 600, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    print("$ " + " ".join(shlex.quote(c) for c in cmd), file=sys.stderr, flush=True)
    if DRY:
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    r = subprocess.run(cmd, capture_output=capture, timeout=timeout)
    if check and r.returncode != 0:
        err = (r.stderr or b"").decode(errors="replace")[-800:]
        raise RuntimeError(f"命令失败（{r.returncode}）：{' '.join(cmd[:4])}…\n{err}")
    return r


def fly_ssh(app: str, command: str, machine: str | None = None, timeout: float = 900) -> bytes:
    cmd = ["fly", "ssh", "console", "-a", app, "-C", command]
    if machine:
        cmd[3:3] = ["--machine", machine]
    return sh(cmd, timeout=timeout).stdout


# ---------- 步骤 ----------

def gw_backup(d: Path) -> None:
    head, blob = parse_stream(fly_ssh(FLY_GW_APP, python_c(REMOTE_GW_BACKUP), timeout=300))
    d.mkdir(parents=True, exist_ok=True)
    (d / "gw.sqlite").write_bytes(blob)
    ok = sqlite3.connect(d / "gw.sqlite").execute("PRAGMA integrity_check").fetchone()[0]
    n = sqlite3.connect(d / "gw.sqlite").execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"网关库 {head['bytes'] / 1e6:.1f} MB，{n} 个用户，integrity_check={ok}")
    if ok != "ok":
        raise SystemExit("备份没通过完整性检查")


def make_plan(d: Path) -> dict:
    db = sqlite3.connect(d / "gw.sqlite")
    old_p = d / "plan.json"
    old = json.loads(old_p.read_text()) if old_p.exists() else {"users": []}
    keep = {u["email"]: u["tenant_id"] for u in old["users"] if u.get("tenant_id")}
    users = []
    for email, status, machine_id, volume_id in db.execute(
            "SELECT email, status, machine_id, volume_id FROM users ORDER BY email"):
        has = bool(machine_id and volume_id)
        users.append({"email": email, "status": status, "machine_id": machine_id, "volume_id": volume_id,
                      "tenant_id": (keep.get(email) or "t" + secrets.token_hex(10)) if has else None})
    # 上一版分配过、这一版没了的账户号（彩排之后删了账户 / 重置了）：导入作业会把 GCP 上的旧副本删掉
    now_ids = {u["tenant_id"] for u in users if u["tenant_id"]}
    retired = sorted((set(keep.values()) | set(old.get("retired", []))) - now_ids)
    plan = {"created": old.get("created") or time.time(), "updated": time.time(), "users": users, "retired": retired}
    old_p.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    moved = len(now_ids)
    print(f"{len(users)} 个用户，{moved} 个有数据要搬，{len(users) - moved} 个从没开通过（到 GCP 后首次登录自动开通）"
          + (f"；{len(retired)} 个旧账户号作废（导入时删掉 GCP 上的彩排副本）" if retired else ""))
    return plan


def export_one(d: Path, u: dict, keep_running: bool) -> dict:
    tid, mid = u["tenant_id"], u["machine_id"]
    t0 = time.time()
    sh(["fly", "machine", "start", mid, "-a", FLY_USERS_APP], check=False, timeout=120)  # 已在跑也没关系
    last: Exception | None = None
    for attempt in range(6):                                  # 刚启动的机器要几秒才接得上 ssh
        try:
            head, blob = parse_stream(fly_ssh(FLY_USERS_APP, python_c(REMOTE_EXPORT, "/data", "freeze"), machine=mid))
            break
        except Exception as e:                                # noqa: BLE001
            last = e
            time.sleep(10 * (attempt + 1))
    else:
        return {"ok": False, "error": str(last)[:500]}
    if DRY:
        return {"ok": True, "dry_run": True}
    local = manifest_of_tar(blob)
    if local != head["manifest"]:
        return {"ok": False, "error": "打包内容与远端清单不一致"}
    users = d / "users"
    users.mkdir(parents=True, exist_ok=True)
    (users / f"{tid}.tar.gz").write_bytes(blob)
    (users / f"{tid}.manifest.json").write_text(json.dumps(head["manifest"], indent=0))
    if not keep_running:
        sh(["fly", "machine", "stop", mid, "-a", FLY_USERS_APP], check=False, timeout=120)
    return {"ok": True, "files": head["files"], "bytes": head["bytes"], "frozen": len(head["pids"]),
            "seconds": round(time.time() - t0, 1)}


def export(d: Path, only: list[str] | None, jobs: int, keep_running: bool) -> None:
    plan = json.loads((d / "plan.json").read_text())
    todo = [u for u in plan["users"] if u.get("tenant_id") and (not only or u["email"] in only)]
    ids = {u["tenant_id"] for u in plan["users"] if u.get("tenant_id")}
    for f in (d / "users").glob("*") if (d / "users").is_dir() else []:
        if f.name.split(".")[0] not in ids and not DRY:          # 已删账户的旧打包不再上传
            f.unlink()
    log_p = d / "export.json"
    log = json.loads(log_p.read_text()) if log_p.exists() else {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for u, res in zip(todo, pool.map(lambda x: export_one(d, x, keep_running), todo)):
            log[u["email"]] = {"tenant_id": u["tenant_id"], "at": time.time(), **res}
            mark = "✓" if res["ok"] else "✗"
            print(f"{mark} {u['email']:36} {res.get('files', '-'):>5} 个文件 "
                  f"{res.get('bytes', 0) / 1e6:7.1f} MB  {res.get('error', '')}", flush=True)
            if not DRY:
                log_p.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    bad = [e for e in (u["email"] for u in todo) if not log.get(e, {}).get("ok")]
    total = sum(v.get("bytes", 0) for v in log.values())
    print(f"导出 {len(todo) - len(bad)}/{len(todo)} 个，共 {total / 1e6:.1f} MB")
    if bad:
        raise SystemExit("没导出成功的（重跑：export --only …）：" + " ".join(bad))


class Gcp:
    def __init__(self, a: argparse.Namespace):
        self.env, self.region = a.env, a.region
        self.project = a.project or f"jl-{a.env}"
        self.bucket = f"{self.project}-migration"

    def batch_uri(self, batch: str) -> str:
        return f"gs://{self.bucket}/cutover/{batch}"

    def job(self, name: str, args: list[str], timeout: float = 4 * 3600) -> None:
        cmd = ["gcloud", "run", "jobs", "execute", f"jl-{self.env}-{name}", "--project", self.project,
               "--region", self.region, "--wait"]
        if args:
            cmd.append("--args=^|^" + "|".join(args))           # 自定义分隔符：参数里可以有逗号
        sh(cmd, timeout=timeout, capture=False)

    def cat(self, uri: str) -> bytes:
        return sh(["gcloud", "storage", "cat", uri, "--project", self.project]).stdout


def upload(g: Gcp, d: Path, batch: str) -> None:
    sh(["gcloud", "storage", "rsync", str(d), g.batch_uri(batch), "--recursive", "--project", g.project,
        "--exclude", r"export\.json$"], timeout=4 * 3600, capture=False)
    print(f"已上传到 {g.batch_uri(batch)}")


def run_import(g: Gcp, batch: str, only: list[str] | None) -> None:
    args = [g.batch_uri(batch)] + (["--only", *only] if only else [])
    try:
        g.job("cutover", args)
    finally:
        if not DRY:
            rep = json.loads(g.cat(g.batch_uri(batch) + "/report.json"))
            s = rep["summary"]
            print(f"导入报告：{s['ok']}/{s['planned']} 全绿")
            for tid, r in sorted(rep["tenants"].items()):
                if not r.get("ok"):
                    print(f"  ✗ {r.get('email')} {tid}: {r.get('error')}")


def gateway(g: Gcp, batch: str, force: bool) -> None:
    b = g.batch_uri(batch)
    g.job("gw-cutover", [f"{b}/gw.sqlite", f"{b}/plan.json", f"{b}/report.json"] + (["--force"] if force else []),
          timeout=3600)


def maintenance(a: argparse.Namespace) -> None:
    words = ["maintenance", a.state, *a.note]
    if a.where == "fly":
        print(fly_ssh(FLY_GW_APP, "python -m gw.cli " + " ".join(shlex.quote(w) for w in words), timeout=120)
              .decode(errors="replace"))
    else:
        Gcp(a).job("gw-cli", words, timeout=600)


def main(argv: list[str]) -> None:
    global DRY
    ap = argparse.ArgumentParser(prog="cutover.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="prod", choices=["prod", "staging"])
    ap.add_argument("--project")
    ap.add_argument("--region", default="asia-southeast1")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gw-backup", "plan"):
        sub.add_parser(name).add_argument("--dir", required=True, type=Path)
    p = sub.add_parser("export")
    p.add_argument("--dir", required=True, type=Path)
    p.add_argument("--only", nargs="*")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--keep-running", action="store_true", help="导出后不停机（彩排时用，用户照常用）")
    p = sub.add_parser("upload")
    p.add_argument("--dir", required=True, type=Path)
    p.add_argument("--batch", required=True)
    p = sub.add_parser("import")
    p.add_argument("--batch", required=True)
    p.add_argument("--only", nargs="*")
    p = sub.add_parser("gateway")
    p.add_argument("--batch", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("maintenance")
    p.add_argument("state", choices=["on", "off", "status"])
    p.add_argument("note", nargs="*")
    p.add_argument("--where", required=True, choices=["fly", "gcp"])
    a = ap.parse_args(argv)
    DRY = a.dry_run
    if a.cmd == "gw-backup":
        gw_backup(a.dir)
    elif a.cmd == "plan":
        make_plan(a.dir)
    elif a.cmd == "export":
        export(a.dir, a.only, a.jobs, a.keep_running)
    elif a.cmd == "upload":
        upload(Gcp(a), a.dir, a.batch)
    elif a.cmd == "import":
        run_import(Gcp(a), a.batch, a.only)
    elif a.cmd == "gateway":
        gateway(Gcp(a), a.batch, a.force)
    elif a.cmd == "maintenance":
        maintenance(a)


if __name__ == "__main__":
    main(sys.argv[1:])
