"""网关的唯一状态：一个 SQLite 文件（Fly 卷上）。用户、邀请、额度、用量全在这里。

额度模型：credit_usd 是累计授予的额度（免费试用 + 日后充值），spent_usd 是累计花费；
余额 = credit - spent。充值 / 订阅最终都落成「给 credit 加数」，计量这边不用改。
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  email          TEXT PRIMARY KEY,
  status         TEXT NOT NULL DEFAULT 'new',     -- new | provisioning | ready | failed
  machine_id     TEXT,
  volume_id      TEXT,
  gateway_token  TEXT NOT NULL,                   -- 网关→machine 的专属口令（machine 端校验）
  meter_key_hash TEXT NOT NULL,                   -- machine→计量 的子 key（只存哈希）
  credit_usd     REAL NOT NULL DEFAULT 0,
  spent_usd      REAL NOT NULL DEFAULT 0,
  error          TEXT,
  created_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (email TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS waitlist (                -- 没邀请就来登录的人（被拦下）
  email TEXT PRIMARY KEY, attempts INTEGER NOT NULL, first_at REAL NOT NULL, last_at REAL NOT NULL,
  lang TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, message TEXT NOT NULL, page TEXT, lang TEXT, user_agent TEXT,
  emailed INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, amount_usd REAL NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL
);
"""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class User:
    email: str
    status: str
    machine_id: str | None
    volume_id: str | None
    gateway_token: str
    meter_key_hash: str
    credit_usd: float
    spent_usd: float
    error: str | None
    consented_at: float | None = None
    privacy_version: str | None = None
    lang: str | None = None                  # 最近一次登录时的界面语言（发通知邮件用）
    low_notified_at: float | None = None     # 已发过「额度快用完」提醒；加额度后清空

    @property
    def balance_usd(self) -> float:
        return self.credit_usd - self.spent_usd


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        for col in ("consented_at REAL", "privacy_version TEXT",     # 旧库就地加列
                    "lang TEXT", "low_notified_at REAL"):
            try:
                self.db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        self.lock = threading.Lock()

    def _user(self, row) -> User | None:
        if row is None:
            return None
        return User(**{k: row[k] for k in User.__dataclass_fields__})

    # ---------- 邀请 ----------

    def invite(self, email: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO invites VALUES (?, ?)", (email.lower(), time.time()))
        self.db.execute("DELETE FROM waitlist WHERE email=?", (email.lower(),))

    def is_invited(self, email: str) -> bool:
        return self.db.execute("SELECT 1 FROM invites WHERE email=?",
                               (email.lower(),)).fetchone() is not None

    def uninvite(self, email: str) -> bool:
        return self.db.execute("DELETE FROM invites WHERE email=?", (email.lower(),)).rowcount > 0

    def record_blocked(self, email: str, lang: str = "") -> bool:
        """记下一次被拦的登录；返回 True 表示此人第一次被拦（该通知管理员了）。"""
        e, now = email.lower(), time.time()
        with self.lock:
            first = self.db.execute("SELECT 1 FROM waitlist WHERE email=?", (e,)).fetchone() is None
            self.db.execute("INSERT INTO waitlist VALUES (?, 1, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
                            "attempts=attempts+1, last_at=excluded.last_at, lang=excluded.lang", (e, now, now, lang))
        return first

    def waitlist(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM waitlist ORDER BY last_at DESC")]

    def dismiss(self, email: str) -> bool:
        return self.db.execute("DELETE FROM waitlist WHERE email=?", (email.lower(),)).rowcount > 0

    # ---------- 用户 ----------

    def get(self, email: str) -> User | None:
        return self._user(self.db.execute("SELECT * FROM users WHERE email=?",
                                          (email.lower(),)).fetchone())

    def by_meter_key(self, key: str) -> User | None:
        return self._user(self.db.execute("SELECT * FROM users WHERE meter_key_hash=?",
                                          (hash_key(key),)).fetchone())

    def all(self) -> list[User]:
        return [self._user(r) for r in self.db.execute("SELECT * FROM users ORDER BY created_at")]

    def create(self, email: str, free_credit: float) -> tuple[User, str]:
        """新建用户；返回 (user, 子 key 明文)。明文只此一次，随即写进该用户 machine 的环境变量。"""
        meter_key = "jlm-" + secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute(
                "INSERT INTO users (email, gateway_token, meter_key_hash, created_at) VALUES (?,?,?,?)",
                (email.lower(), secrets.token_urlsafe(32), hash_key(meter_key), time.time()))
            self._grant(email, free_credit, "免费试用")
        return self.get(email), meter_key

    def rotate_meter_key(self, email: str) -> str:
        meter_key = "jlm-" + secrets.token_urlsafe(32)
        self.db.execute("UPDATE users SET meter_key_hash=? WHERE email=?",
                        (hash_key(meter_key), email.lower()))
        return meter_key

    def set_status(self, email: str, status: str, *, machine_id: str | None = None,
                   volume_id: str | None = None, error: str | None = None) -> None:
        sets, args = ["status=?", "error=?"], [status, error]
        if machine_id is not None:
            sets.append("machine_id=?"); args.append(machine_id)
        if volume_id is not None:
            sets.append("volume_id=?"); args.append(volume_id)
        self.db.execute(f"UPDATE users SET {', '.join(sets)} WHERE email=?", (*args, email.lower()))

    def clear_machine(self, email: str) -> None:
        """重置后回到「新用户」：机器与卷的记录清空、换一把网关口令；额度与用量原样保留
        （否则重置一下就能反复白拿试用额度）。"""
        self.db.execute("UPDATE users SET status='new', machine_id=NULL, volume_id=NULL, error=NULL, "
                        "gateway_token=? WHERE email=?", (secrets.token_urlsafe(32), email.lower()))

    # ---------- 额度 ----------

    def _grant(self, email: str, amount: float, reason: str) -> None:
        if amount:
            self.db.execute("INSERT INTO grants (email, amount_usd, reason, at) VALUES (?,?,?,?)",
                            (email.lower(), amount, reason, time.time()))
            self.db.execute("UPDATE users SET credit_usd = credit_usd + ?, low_notified_at = NULL "
                            "WHERE email=?", (amount, email.lower()))

    def grant(self, email: str, amount: float, reason: str) -> None:
        with self.lock:
            self._grant(email, amount, reason)

    def charge(self, email: str, model: str, prompt: int, completion: int, cost: float,
               low_at: float | None = None) -> bool:
        """记账。给了 low_at 时：余额这次跌破 low_at 且还没提醒过 → 记下已提醒并返回 True。"""
        e = email.lower()
        with self.lock:
            self.db.execute("INSERT INTO usage (email, model, prompt_tokens, completion_tokens, "
                            "cost_usd, at) VALUES (?,?,?,?,?,?)",
                            (e, model, prompt, completion, cost, time.time()))
            self.db.execute("UPDATE users SET spent_usd = spent_usd + ? WHERE email=?", (cost, e))
            if low_at is None:
                return False
            return self.db.execute("UPDATE users SET low_notified_at = ? WHERE email=? AND low_notified_at IS NULL "
                                   "AND credit_usd - spent_usd < ?", (time.time(), e, low_at)).rowcount > 0

    def set_lang(self, email: str, lang: str) -> None:
        self.db.execute("UPDATE users SET lang=? WHERE email=?", (lang, email.lower()))

    def blocked_lang(self, email: str) -> str | None:
        r = self.db.execute("SELECT lang FROM waitlist WHERE email=?", (email.lower(),)).fetchone()
        return r[0] if r else None

    # ---------- 反馈 ----------

    def add_feedback(self, email: str, message: str, page: str, lang: str, ua: str) -> int:
        cur = self.db.execute("INSERT INTO feedback (email, message, page, lang, user_agent, at) "
                              "VALUES (?,?,?,?,?,?)", (email.lower(), message, page, lang, ua, time.time()))
        return cur.lastrowid

    def mark_feedback_emailed(self, fid: int) -> None:
        self.db.execute("UPDATE feedback SET emailed=1 WHERE id=?", (fid,))

    def feedback_count_since(self, email: str, since: float) -> int:
        return self.db.execute("SELECT COUNT(*) FROM feedback WHERE email=? AND at>=?",
                               (email.lower(), since)).fetchone()[0]

    def list_feedback(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,))]

    def recent_usage(self, email: str, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT model, prompt_tokens, completion_tokens, cost_usd, at FROM usage "
            "WHERE email=? ORDER BY id DESC LIMIT ?", (email.lower(), limit))]

    def usage_since(self, email: str, since: float) -> list[dict]:
        """用量明细页按天汇总用：只要时间与金额，不要 token 数。"""
        return [dict(r) for r in self.db.execute(
            "SELECT model, cost_usd, at FROM usage WHERE email=? AND at>=? ORDER BY at DESC",
            (email.lower(), since))]

    # ---------- 管理后台 ----------

    def admin_snapshot(self, since: float) -> dict:
        """后台要的全部数字：账户汇总（不含口令与 key 哈希）、since 以来的逐条用量、名单、反馈、发放记录。"""
        q = lambda sql, *a: [dict(r) for r in self.db.execute(sql, a)]            # noqa: E731
        return {
            "users": q("SELECT u.email, u.status, u.lang, u.credit_usd, u.spent_usd, u.created_at, u.consented_at, "
                       "u.privacy_version, u.machine_id, u.error, u.low_notified_at, "
                       "MAX(g.at) AS last_at, COUNT(g.id) AS calls FROM users u "
                       "LEFT JOIN usage g ON g.email = u.email GROUP BY u.email ORDER BY last_at DESC, u.created_at DESC"),
            "usage": q("SELECT email, model, prompt_tokens, completion_tokens, cost_usd, at FROM usage "
                       "WHERE at >= ? ORDER BY at", since),
            "waitlist": self.waitlist(),
            "pending_invites": q("SELECT i.email, i.created_at FROM invites i LEFT JOIN users u ON u.email = i.email "
                                 "WHERE u.email IS NULL ORDER BY i.created_at DESC"),
            "feedback": self.list_feedback(20),
            "grants": q("SELECT email, amount_usd, reason, at FROM grants ORDER BY id DESC LIMIT 20"),
        }

    # ---------- 隐私：同意、导出、彻底删除 ----------

    def consent(self, email: str, version: str) -> None:
        self.db.execute("UPDATE users SET consented_at=?, privacy_version=? WHERE email=?",
                        (time.time(), version, email.lower()))

    def export(self, email: str) -> dict:
        """网关这边关于此人的全部记录（口令与 key 哈希不导出——那是系统凭据，不是个人数据）。"""
        e = email.lower()
        u = self.db.execute("SELECT email, status, credit_usd, spent_usd, created_at, consented_at, "
                            "privacy_version, lang FROM users WHERE email=?", (e,)).fetchone()
        q = lambda sql: [dict(r) for r in self.db.execute(sql, (e,))]          # noqa: E731
        return {"account": dict(u) if u else None,
                "invited": self.is_invited(e),
                "grants": q("SELECT amount_usd, reason, at FROM grants WHERE email=? ORDER BY id"),
                "usage": q("SELECT model, prompt_tokens, completion_tokens, cost_usd, at FROM usage "
                           "WHERE email=? ORDER BY id"),
                "feedback": q("SELECT message, page, lang, user_agent, at FROM feedback WHERE email=? ORDER BY id")}

    def delete_user(self, email: str) -> None:
        """彻底删除：账户、邀请、额度流水、用量、反馈一并删掉。机器与卷由调用方先销毁。"""
        e = email.lower()
        with self.lock:
            for t in ("usage", "grants", "feedback", "invites", "waitlist", "users"):
                self.db.execute(f"DELETE FROM {t} WHERE email=?", (e,))
