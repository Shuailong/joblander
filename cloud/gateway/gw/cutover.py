"""切流：把 Fly 网关的 SQLite 库搬进 GCP 网关库（Cloud SQL）。在 GCP 里以 Cloud Run 作业跑（网关镜像）：

  python -m gw.cutover <gw.sqlite> <plan.json> <report.json> [--force]

三个参数都可以是 gs:// 路径（迁移桶里 deploy/gcp/cutover.py 上传的那一批）。

- 每张表原样复制，整个过程一个事务：中途出错目标库原样不动；
- users：plan 里有账户号的人，volume_id 换成账户号、machine_id = shared、status = ready；
  没有数据要搬的人（从没开通过）回到 new，下次登录自动开通；
- 引擎那边的导入报告（report.json）里每个账户都要是全绿，否则拒绝——不然那个人登录会看到一个空账户；
- 目标库里有比 Fly 备份更新的活动记录（说明 GCP 已经在服务用户）时拒绝，除非 --force；
- 源库有、目标库没有的列直接报错（镜像版本不对，会丢数据）；复制完逐表核对行数，自增序列接到最大 id 之后。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
# 用来判断「哪边的数据更新」的活动时间列
ACTIVITY = {"usage": "at", "events": "last_at", "geo": "at", "feedback": "at", "waitlist": "last_at",
            "mail_queue": "created_at", "ai_errors": "at"}


def fetch(uri: str, workdir: Path) -> Path:
    """gs:// 路径下载到本地；本地路径原样返回。"""
    if not uri.startswith("gs://"):
        return Path(uri)
    import httpx
    bucket, _, name = uri[5:].partition("/")
    tok = httpx.get(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=10).json()["access_token"]
    dest = workdir / Path(name).name
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{urllib.parse.quote(name, safe='')}?alt=media"
    with httpx.stream("GET", url, headers={"Authorization": f"Bearer {tok}"}, timeout=600) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest


class Target:
    """目标库：Postgres（线上）或 SQLite（测试）。用原生连接开一个事务，不走 store 的兼容层。"""

    def __init__(self, target: str):
        self.pg = target.startswith(("postgresql://", "postgres://")) or "host=" in target
        if self.pg:
            import psycopg
            self.conn = psycopg.connect(target, prepare_threshold=None)
        else:
            self.conn = sqlite3.connect(target, isolation_level="DEFERRED")
        self.ph = "%s" if self.pg else "?"

    def rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        cur = self.conn.cursor()
        cur.execute(sql.replace("?", self.ph), args)
        return list(cur.fetchall())

    def tables(self) -> set[str]:
        if self.pg:
            return {r[0] for r in self.rows("SELECT table_name FROM information_schema.tables "
                                             "WHERE table_schema = current_schema()")}
        return {r[0] for r in self.rows("SELECT name FROM sqlite_master WHERE type='table'")}

    def columns(self, table: str) -> list[str]:
        if self.pg:
            return [r[0] for r in self.rows("SELECT column_name FROM information_schema.columns WHERE "
                                            "table_schema = current_schema() AND table_name = ? "
                                            "ORDER BY ordinal_position", (table,))]
        return [r[1] for r in self.rows(f"PRAGMA table_info({table})")]

    def count(self, table: str) -> int:
        return self.rows(f"SELECT COUNT(*) FROM {table}")[0][0]

    def clear(self, tables: list[str]) -> None:
        cur = self.conn.cursor()
        if self.pg:
            cur.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY")
        else:
            for t in tables:
                cur.execute(f"DELETE FROM {t}")

    def insert(self, table: str, cols: list[str], rows: list[tuple]) -> None:
        if not rows:
            return
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join([self.ph] * len(cols))})"
        cur = self.conn.cursor()
        for i in range(0, len(rows), 500):
            cur.executemany(sql, rows[i:i + 500])

    def fix_sequence(self, table: str) -> None:
        if self.pg:
            self.conn.cursor().execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")


def newest(rows_of, tables: set[str]) -> float:
    best = 0.0
    for t, col in ACTIVITY.items():
        if t in tables:
            v = rows_of(f"SELECT MAX({col}) FROM {t}")[0][0]
            best = max(best, float(v or 0))
    return best


def check_report(plan: dict, report: dict) -> list[str]:
    """plan 里每个要搬的账户，导入报告里都得是 ok。返回有问题的说明。"""
    got = report.get("tenants", {})
    bad = []
    for u in plan["users"]:
        tid = u.get("tenant_id")
        if tid and not (got.get(tid) or {}).get("ok"):
            bad.append(f"{u['email']}（{tid}）：{(got.get(tid) or {}).get('error') or '报告里没有或对不上'}")
    return bad


def copy(src_path: str | Path, target: str, plan: dict, report: dict, force: bool = False) -> dict[str, int]:
    from gw.store import Store
    if bad := check_report(plan, report):
        raise SystemExit("引擎导入还没全绿，先处理这些账户（deploy/gcp/cutover.py import --only …）：\n  "
                         + "\n  ".join(bad))
    Store(target).db.close()                   # 建表 / 补列：与线上网关同一份代码
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = Target(target)
    try:
        src_tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        dst_tables = dst.tables()
        if missing := [t for t in src_tables if t not in dst_tables]:
            raise SystemExit(f"目标库没有这些表：{missing}（网关镜像版本比 Fly 上的旧？）")
        if not force and dst.count("users"):
            mine = newest(dst.rows, dst_tables)
            theirs = newest(lambda q: src.execute(q).fetchall(), set(src_tables))
            if mine > theirs + 60:
                raise SystemExit("GCP 网关库里有比这份 Fly 备份更新的活动记录——像是已经切流在服务用户了。"
                                 "确定要用旧备份覆盖，加 --force。")
        by_email = {u["email"].lower(): u for u in plan["users"]}
        plans: dict[str, tuple[list[str], list[tuple]]] = {}
        for t in src_tables:
            src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
            dst_cols = set(dst.columns(t))
            if lost := [c for c in src_cols if c not in dst_cols]:
                raise SystemExit(f"{t} 表在目标库少了列 {lost}（网关镜像版本比 Fly 上的旧？）")
            rows = src.execute(f"SELECT {', '.join(src_cols)} FROM {t}").fetchall()
            if t == "users":
                rows = [_map_user(dict(zip(src_cols, r)), by_email, src_cols) for r in rows]
            plans[t] = (src_cols, [tuple(r) for r in rows])
        dst.clear(src_tables)
        for t, (cols, rows) in plans.items():
            dst.insert(t, cols, rows)
            if "id" in cols:
                dst.fix_sequence(t)
        counts = {t: dst.count(t) for t in src_tables}
        if off := {t: (len(plans[t][1]), n) for t, n in counts.items() if n != len(plans[t][1])}:
            raise SystemExit(f"行数对不上（源, 目标）：{off}")
        dst.conn.commit()
        return counts
    except BaseException:
        dst.conn.rollback()
        raise
    finally:
        src.close()
        dst.conn.close()


def _map_user(row: dict[str, Any], by_email: dict[str, dict], cols: list[str]) -> tuple:
    p = by_email.get(str(row["email"]).lower())
    if p and p.get("tenant_id"):
        row.update(volume_id=p["tenant_id"], machine_id="shared", status="ready", error=None)
    else:                                       # 没有数据要搬：下次登录按新用户开通（额度与用量照留）
        row.update(volume_id=None, machine_id=None, status="new", error=None)
    return tuple(row[c] for c in cols)


def main(argv: list[str]) -> None:
    from gw.main import db_target
    force = "--force" in argv
    args = [a for a in argv if a != "--force"]
    if len(args) != 3:
        raise SystemExit(__doc__)
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        src, plan_p, report_p = (fetch(a, work) for a in args)
        plan = json.loads(Path(plan_p).read_text())
        report = json.loads(Path(report_p).read_text())
        counts = copy(src, db_target(), plan, report, force=force)
    moved = sum(1 for u in plan["users"] if u.get("tenant_id"))
    print(json.dumps({"ok": True, "tables": counts, "users_with_data": moved}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
