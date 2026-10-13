"""网关数据库连接：Fly 上是卷上的 SQLite 文件，GCP 上是 Cloud SQL（Postgres）。

store.py 的 SQL 是照 SQLite 写的。这里给 Postgres 包一层「像 sqlite3 连接一样用」的外壳，
把用到的几处 SQLite 方言就地翻译，store.py 只需把 sqlite3.connect 换成 db.connect：
- `?` 占位符 → `%s`（SQL 里原有的 % 先转义）
- INSERT OR IGNORE → ON CONFLICT DO NOTHING；INSERT OR REPLACE → ON CONFLICT (主键) DO UPDATE
- 两个参数的 MIN / MAX（SQLite 的标量用法）→ LEAST / GREATEST
- 建表类型：INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY，INTEGER → BIGINT，REAL → DOUBLE PRECISION
- cursor.lastrowid → INSERT … RETURNING id
- ORDER BY … DESC 补上 NULLS LAST（SQLite 里 NULL 最小，倒序时排在最后）
- ALTER TABLE 加已存在的列 → 抛 sqlite3.OperationalError（store.py 靠它判断「旧库已有此列」）
- PRAGMA → 忽略
连接断了（Cloud SQL 维护或高可用切换）自动重连并重试一次。
"""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Iterable

# 主键：INSERT OR REPLACE 翻译成 ON CONFLICT 时要用
PRIMARY_KEYS = {
    "users": ["email"], "invites": ["email"], "waitlist": ["email"], "active_days": ["email", "day"],
    "events": ["email", "name", "day"], "geo": ["email"], "kv": ["k"],
}


def connect(target: str) -> Any:
    """target 是 postgres 连接串就连 Postgres，否则当 SQLite 文件路径。"""
    if target.startswith(("postgresql://", "postgres://")) or "host=" in target:
        return PgCompat(target)
    conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


class Row:
    """行为与 sqlite3.Row 一致：按列名或位置取值，迭代得到值，keys() 给列名，dict(row) 可用。"""

    __slots__ = ("_names", "_values", "_index")

    def __init__(self, names: list[str], values: Iterable[Any]):
        self._names = list(names)
        self._values = tuple(values)
        self._index = {n: i for i, n in enumerate(self._names)}

    def keys(self) -> list[str]:
        return list(self._names)

    def __getitem__(self, k: Any) -> Any:
        if isinstance(k, (int, slice)):
            return self._values[k]
        return self._values[self._index[k]]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values))!r})"


class Cursor:
    def __init__(self, rows: list[Row], rowcount: int, lastrowid: int | None):
        self._rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchone(self) -> Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Row]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


_INSERT = re.compile(r"^\s*INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO\s+(\w+)", re.IGNORECASE)
_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_MINMAX2 = re.compile(r"\b(MIN|MAX)\(\s*([\w.]+)\s*,\s*([\w.]+)\s*\)", re.IGNORECASE)
_DESC = re.compile(r"\bDESC\b(?!\s+NULLS)", re.IGNORECASE)
_ALTER_ADD = re.compile(r"^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.IGNORECASE)


def _types(sql: str) -> str:
    sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bINTEGER\b", "BIGINT", sql, flags=re.IGNORECASE)
    return re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.IGNORECASE)


_UPSERT = re.compile(r"\bDO\s+UPDATE\s+SET\s+(.*)$", re.IGNORECASE | re.DOTALL)


def _split_top(text: str) -> list[str]:
    """按顶层逗号切（括号里的逗号不切）。"""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _qualify_upsert(sql: str, table: str, cols: list[str]) -> str:
    """ON CONFLICT … DO UPDATE SET 右边的列名在 Postgres 里有歧义（目标表 vs excluded）：
    没加前缀的一律指向目标表现有的行（SQLite 的语义），补上「表名.」。"""
    m = _UPSERT.search(sql)
    if not m or not cols:
        return sql
    names = "|".join(sorted(map(re.escape, cols), key=len, reverse=True))
    bare = re.compile(rf"(?<![\w.])({names})\b(?!\s*\()")
    parts = []
    for assign in _split_top(m.group(1)):
        lhs, eq, rhs = assign.partition("=")
        parts.append(f"{lhs}{eq}{bare.sub(lambda x: f'{table}.{x.group(1)}', rhs)}" if eq else assign)
    return sql[:m.start(1)] + ",".join(parts)


def translate(sql: str, columns: dict[str, list[str]]) -> tuple[str, bool]:
    """SQLite 方言 → Postgres。返回 (语句, 是否需要取回新行 id)。"""
    s = sql.replace("%", "%%").replace("?", "%s")
    s = _MINMAX2.sub(lambda m: f"{'LEAST' if m.group(1).upper() == 'MIN' else 'GREATEST'}"
                               f"({m.group(2)}, {m.group(3)})", s)
    m = _INSERT.match(s)
    if m:
        kind, table = m.group(1).upper(), m.group(2)
        s = _INSERT.sub(f"INSERT INTO {table}", s, count=1)
        if kind == "IGNORE":
            s += " ON CONFLICT DO NOTHING"
        else:
            pk = PRIMARY_KEYS[table]
            cols = [c for c in columns.get(table, []) if c not in pk]
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            s += f" ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {sets}" if sets else \
                 f" ON CONFLICT ({', '.join(pk)}) DO NOTHING"
    m_ins = _INSERT_TABLE.match(s)
    if m_ins:
        s = _qualify_upsert(s, m_ins.group(1), columns.get(m_ins.group(1), []))
    if re.search(r"\bORDER\s+BY\b", s, re.IGNORECASE):
        s = _DESC.sub("DESC NULLS LAST", s)
    m = _INSERT_TABLE.match(s)
    wants_id = bool(m) and "id" in columns.get(m.group(1), []) and "RETURNING" not in s.upper()
    if wants_id:
        s += " RETURNING id"
    return s, wants_id


class PgCompat:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._lock = threading.RLock()
        self._conn: Any = None
        self.columns: dict[str, list[str]] = {}
        self.row_factory = None                     # 与 sqlite3 接口对齐，忽略
        self._connect()

    def _connect(self) -> None:
        import psycopg
        self._conn = psycopg.connect(self.dsn, autocommit=True, prepare_threshold=None)
        self._load_columns()

    def _load_columns(self) -> None:
        rows = self._conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position").fetchall()
        cols: dict[str, list[str]] = {}
        for t, c in rows:
            cols.setdefault(t, []).append(c)
        self.columns = cols

    def _run(self, sql: str, params: Iterable[Any] = (), many: bool = False) -> Cursor:
        import psycopg
        stripped = sql.strip()
        if stripped.upper().startswith("PRAGMA"):
            return Cursor([], 0, None)
        alter = _ALTER_ADD.match(stripped)
        if alter:
            table, col = alter.group(1), alter.group(2)
            if col in self.columns.get(table, []):
                raise sqlite3.OperationalError(f"duplicate column name: {col}")
            stripped = _types(stripped)
        text, wants_id = translate(stripped, self.columns)
        with self._lock:
            for attempt in (1, 2):
                try:
                    with self._conn.cursor() as cur:
                        if many:
                            cur.executemany(text, list(params))
                            return Cursor([], cur.rowcount, None)
                        cur.execute(text, tuple(params))
                        rows: list[Row] = []
                        if cur.description is not None:
                            names = [d.name for d in cur.description]
                            rows = [Row(names, r) for r in cur.fetchall()]
                        lastrowid = rows[0]["id"] if wants_id and rows else None
                        if alter:
                            self._load_columns()
                        return Cursor([] if wants_id else rows, cur.rowcount, lastrowid)
                except psycopg.errors.DuplicateColumn as e:
                    raise sqlite3.OperationalError(str(e)) from e
                except psycopg.OperationalError:
                    if attempt == 2 or not self._conn.closed:
                        raise
                    self._connect()                      # 连接断了：重连再试一次
        raise RuntimeError("unreachable")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Cursor:
        return self._run(sql, params)

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> Cursor:
        return self._run(sql, seq, many=True)

    def executescript(self, script: str) -> None:
        for stmt in _split(script):
            self._run(_types(stmt))
        with self._lock:
            self._load_columns()

    def close(self) -> None:
        self._conn.close()


def _split(script: str) -> list[str]:
    """按分号切语句（先去掉行尾 -- 注释；建表语句里没有字符串字面量里的分号）。"""
    lines = [re.sub(r"--.*$", "", line) for line in script.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
