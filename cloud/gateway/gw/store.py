"""网关的唯一状态：Fly 上是卷上的 SQLite 文件，GCP 上是 Cloud SQL（见 db.py）。用户、邀请、额度、用量全在这里。

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
CREATE TABLE IF NOT EXISTS active_days (            -- 哪天用过（只记日期，不记做了什么）：后台的活跃曲线
  email TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (email, day)
);
CREATE TABLE IF NOT EXISTS credit_requests (        -- 用户在应用里申请加额度，管理员在后台批
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',          -- pending | approved | declined
  amount_usd REAL, at REAL NOT NULL, decided_at REAL
);
CREATE TABLE IF NOT EXISTS ai_errors (              -- 上游（OpenAI / 搜索）调用失败：只记状态码与错误类型，不记内容
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, model TEXT NOT NULL, status INTEGER NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (                 -- 产品使用记录：某人某天用了某个功能几次（只有路由模板，不含内容）
  email TEXT NOT NULL, name TEXT NOT NULL, day TEXT NOT NULL,
  n INTEGER NOT NULL, first_at REAL NOT NULL, last_at REAL NOT NULL,
  PRIMARY KEY (email, name, day)
);
CREATE TABLE IF NOT EXISTS geo (                    -- 最近一次登录 / 当天首次访问的 IP 与大致所在地（离线库推算）
  email TEXT PRIMARY KEY, ip TEXT NOT NULL, country TEXT, country_name TEXT, region TEXT, city TEXT,
  lat REAL, lon REAL, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_queue (             -- 给用户的信先排队，网关按每日上限慢慢发；重启不丢
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  to_email TEXT NOT NULL, kind TEXT NOT NULL, lang TEXT, ctx TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',          -- pending | sent | failed
  tries INTEGER NOT NULL DEFAULT 0, error TEXT, created_at REAL NOT NULL, sent_at REAL
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);   -- 零散状态（如每日汇总上次发到哪）
CREATE TABLE IF NOT EXISTS grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, amount_usd REAL NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL
);
"""

MAINTENANCE_KEY = "maintenance"     # kv：维护模式（切流时打开）；值是 {"since": 时间, "note": 说明}


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
    created_at: float = 0.0
    analytics_off: float | None = None       # 隐私 v2：关掉「行为数据」的时间；空 = 开着

    @property
    def balance_usd(self) -> float:
        return self.credit_usd - self.spent_usd


class Store:
    def __init__(self, path: str):
        from gw import db as gwdb
        self.db = gwdb.connect(path)          # SQLite 文件路径（Fly），或 Postgres 连接串（GCP，见 db.py）
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        for col in ("consented_at REAL", "privacy_version TEXT",     # 旧库就地加列
                    "lang TEXT", "low_notified_at REAL", "analytics_off REAL"):
            try:
                self.db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass
        for col in ("requested_at REAL",      # 被拦过的人获邀时记下首次被拦时间（增长曲线用）
                    "mailed_at REAL",         # 邀请邮件发出的时间；空 = 没发出（后台可重发）
                    "lang TEXT"):             # 被拦时的界面语言（获邀后被拦记录就删了，语言留在这里）
            try:
                self.db.execute(f"ALTER TABLE invites ADD COLUMN {col}")
                if col.startswith("mailed_at"):          # 加列之前的邀请当时都发过信了
                    self.db.execute("UPDATE invites SET mailed_at = created_at")
            except sqlite3.OperationalError:
                pass
        self.lock = threading.Lock()

    def _user(self, row) -> User | None:
        if row is None:
            return None
        return User(**{k: row[k] for k in User.__dataclass_fields__})

    # ---------- 邀请 ----------

    def invite(self, email: str) -> None:
        e = email.lower()
        w = self.db.execute("SELECT first_at, lang FROM waitlist WHERE email=?", (e,)).fetchone()
        self.db.execute("INSERT OR IGNORE INTO invites (email, created_at, requested_at, lang) VALUES (?, ?, ?, ?)",
                        (e, time.time(), w["first_at"] if w else None, w["lang"] if w else None))
        self.db.execute("DELETE FROM waitlist WHERE email=?", (email.lower(),))

    def mark_invite_mailed(self, email: str) -> None:
        self.db.execute("UPDATE invites SET mailed_at=? WHERE email=?", (time.time(), email.lower()))

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
        e = email.lower()
        gone = self.db.execute("DELETE FROM waitlist WHERE email=?", (e,)).rowcount > 0
        if gone and not self.get(e) and not self.is_invited(e):           # 被拦的人清掉就不留地点
            self.db.execute("DELETE FROM geo WHERE email=?", (e,))
        return gone

    # ---------- 地点 ----------

    def truncate_ips(self, before: float) -> int:
        """完整 IP 只留到 before 之前：之后清掉 IP，只留国家 / 城市（隐私说明 v2「保存多久」）。"""
        return self.db.execute("UPDATE geo SET ip='' WHERE at < ? AND ip <> ''", (before,)).rowcount

    def set_geo(self, email: str, ip: str, g: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO geo VALUES (?,?,?,?,?,?,?,?,?)",
                        (email.lower(), ip, g.get("country"), g.get("country_name"), g.get("region"),
                         g.get("city"), g.get("lat"), g.get("lon"), time.time()))

    # ---------- 用户 ----------

    def get(self, email: str) -> User | None:
        return self._user(self.db.execute("SELECT * FROM users WHERE email=?",
                                          (email.lower(),)).fetchone())

    def by_meter_key(self, key: str) -> User | None:
        return self._user(self.db.execute("SELECT * FROM users WHERE meter_key_hash=?",
                                          (hash_key(key),)).fetchone())

    def all(self) -> list[User]:
        return [self._user(r) for r in self.db.execute("SELECT * FROM users ORDER BY created_at")]

    def ready_users(self) -> list[User]:
        """有机器、已就绪的用户（休眠 / 叫醒只管这些）。"""
        return [self._user(r) for r in self.db.execute(
            "SELECT * FROM users WHERE status='ready' AND machine_id IS NOT NULL ORDER BY created_at")]

    def create(self, email: str, free_credit: float) -> tuple[User, str]:
        """新建用户；返回 (user, 子 key 明文)。明文只此一次，随即写进该用户 machine 的环境变量。"""
        meter_key = "jlm-" + secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute(
                "INSERT INTO users (email, gateway_token, meter_key_hash, created_at) VALUES (?,?,?,?)",
                (email.lower(), secrets.token_urlsafe(32), hash_key(meter_key), time.time()))
            self._grant(email, free_credit, "免费试用")
        return self.get(email), meter_key

    def by_tenant(self, tenant_id: str) -> User | None:
        """GCP 形态：引擎调计量时用账户 ID 指明是谁（users.volume_id 存的就是账户 ID）。"""
        if not tenant_id:
            return None
        return self._user(self.db.execute("SELECT * FROM users WHERE volume_id=?", (tenant_id,)).fetchone())

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

    def mail_lang(self, email: str) -> str | None:
        """给此人发信用哪种语言：账户的界面语言 → 获邀时记下的 → 被拦时的 → 按 IP 所在国家推断
        （中国大陆 / 港澳台中文，其他英文）→ 都不知道返回 None（中英都放）。"""
        e = email.lower()
        for sql in ("SELECT lang FROM users WHERE email=?", "SELECT lang FROM invites WHERE email=?",
                    "SELECT lang FROM waitlist WHERE email=?"):
            r = self.db.execute(sql, (e,)).fetchone()
            if r and r[0] in ("zh", "en"):
                return r[0]
        r = self.db.execute("SELECT country FROM geo WHERE email=?", (e,)).fetchone()
        if r and r[0]:
            return "zh" if r[0] in ("CN", "HK", "MO", "TW") else "en"
        return None

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
            "active_days": q("SELECT email, day FROM active_days WHERE day >= ?",
                             time.strftime("%Y-%m-%d", time.gmtime(since - 86400))),
            "credit_requests": q("SELECT r.*, u.credit_usd, u.spent_usd FROM credit_requests r "
                                 "LEFT JOIN users u ON u.email = r.email "
                                 "WHERE r.status='pending' OR r.decided_at >= ? ORDER BY r.status != 'pending', r.id DESC",
                                 since),
            "invites": q("SELECT email, created_at, requested_at FROM invites"),
            "ai_errors": q("SELECT email, model, status, kind, at FROM ai_errors WHERE at >= ? ORDER BY at", since),
            "events": q("SELECT email, name, day, n, first_at FROM events"),
            "first_ai": q("SELECT email, MIN(at) AS at FROM usage GROUP BY email"),
            "waitlist": self.waitlist(),
            "pending_invites": q("SELECT i.email, i.created_at, i.mailed_at FROM invites i LEFT JOIN users u ON u.email = i.email "
                                 "WHERE u.email IS NULL ORDER BY i.created_at DESC"),
            "feedback": self.list_feedback(1000),
            "queued_invites": [r["to_email"] for r in q("SELECT DISTINCT to_email FROM mail_queue "
                                                        "WHERE kind='invited' AND status='pending'")],
            "geo": q("SELECT email, ip, country, country_name, region, city, lat, lon, at FROM geo"),
            "grants": q("SELECT email, amount_usd, reason, at FROM grants ORDER BY id DESC LIMIT 2000"),
        }

    # ---------- 发信队列 ----------

    def enqueue_mail(self, to: str, kind: str, lang: str | None, ctx: dict | None = None) -> int:
        import json
        return self.db.execute("INSERT INTO mail_queue (to_email, kind, lang, ctx, created_at) VALUES (?,?,?,?,?)",
                               (to.lower(), kind, lang, json.dumps(ctx or {}), time.time())).lastrowid

    def next_mail(self) -> dict | None:
        import json
        r = self.db.execute("SELECT * FROM mail_queue WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        return {**dict(r), "ctx": json.loads(r["ctx"])} if r else None

    def mail_done(self, mid: int) -> None:
        self.db.execute("UPDATE mail_queue SET status='sent', sent_at=?, error=NULL WHERE id=?", (time.time(), mid))

    def mail_retry(self, mid: int, error: str, give_up_after: int = 5) -> None:
        """记一次失败；失败满 give_up_after 次就不再试（status=failed）。"""
        self.db.execute("UPDATE mail_queue SET tries=tries+1, error=?, "
                        "status=CASE WHEN tries+1 >= ? THEN 'failed' ELSE status END WHERE id=?",
                        (error[:300], give_up_after, mid))

    def mail_pending(self, to: str, kind: str) -> bool:
        return self.db.execute("SELECT 1 FROM mail_queue WHERE to_email=? AND kind=? AND status='pending'",
                               (to.lower(), kind)).fetchone() is not None

    def mail_stats(self, since: float) -> dict:
        one = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]                  # noqa: E731
        return {"pending": one("SELECT COUNT(*) FROM mail_queue WHERE status='pending'"),
                "sent": one("SELECT COUNT(*) FROM mail_queue WHERE status='sent' AND sent_at >= ?", since),
                "failed": one("SELECT COUNT(*) FROM mail_queue WHERE status='failed' AND created_at >= ?", since)}

    def prune_mail(self, before: float) -> None:
        """发完 / 放弃的老记录不留（只用来算最近 24 小时发了几封）。"""
        self.db.execute("DELETE FROM mail_queue WHERE status != 'pending' AND created_at < ?", (before,))

    def get_kv(self, k: str) -> str | None:
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None

    def set_kv(self, k: str, v: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, v))

    def kv_items(self, prefix: str) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT k, v FROM kv WHERE k LIKE ? ORDER BY k", (prefix + "%",)).fetchall()
        return [(r["k"], r["v"]) for r in rows if r["k"].startswith(prefix)]

    def del_kv(self, k: str) -> None:
        self.db.execute("DELETE FROM kv WHERE k=?", (k,))

    def digest_since(self, since: float) -> dict:
        """每日汇总邮件的内容：since 以来新被拦的人、新的额度申请（还待批的）、新反馈。"""
        q = lambda sql, *a: [dict(r) for r in self.db.execute(sql, a)]            # noqa: E731
        return {
            "blocked": q("SELECT email, lang, attempts, first_at FROM waitlist WHERE first_at >= ? ORDER BY first_at",
                         since),
            "requests": q("SELECT r.id, r.email, r.message, r.at, u.credit_usd, u.spent_usd FROM credit_requests r "
                          "LEFT JOIN users u ON u.email = r.email WHERE r.status='pending' AND r.at >= ? ORDER BY r.id",
                          since),
            "feedback": q("SELECT id, email, message, page, at FROM feedback WHERE at >= ? ORDER BY id", since),
            "waiting": self.db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0],
            "pending": self.db.execute("SELECT COUNT(*) FROM credit_requests WHERE status='pending'").fetchone()[0],
        }

    # ---------- 额度申请 ----------

    def request_credit(self, email: str, message: str) -> int | None:
        """新申请；已有一条待批的就不再收（返回 None）。"""
        e = email.lower()
        with self.lock:
            if self.db.execute("SELECT 1 FROM credit_requests WHERE email=? AND status='pending'", (e,)).fetchone():
                return None
            return self.db.execute("INSERT INTO credit_requests (email, message, at) VALUES (?,?,?)",
                                   (e, message, time.time())).lastrowid

    def latest_request(self, email: str) -> dict | None:
        r = self.db.execute("SELECT id, status, amount_usd, at, decided_at FROM credit_requests WHERE email=? "
                            "ORDER BY id DESC LIMIT 1", (email.lower(),)).fetchone()
        return dict(r) if r else None

    def credit_request(self, rid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM credit_requests WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def decide_request(self, rid: int, approve: bool, amount: float, reason: str) -> dict | None:
        """批（同时发额度）或不批；只对待批的生效，返回那条申请。"""
        with self.lock:
            r = self.db.execute("SELECT * FROM credit_requests WHERE id=? AND status='pending'", (rid,)).fetchone()
            if r is None:
                return None
            if approve:
                self._grant(r["email"], amount, reason)
            self.db.execute("UPDATE credit_requests SET status=?, amount_usd=?, decided_at=? WHERE id=?",
                            ("approved" if approve else "declined", amount if approve else None, time.time(), rid))
        return dict(r)

    # ---------- 上游失败 ----------

    def record_ai_error(self, email: str, model: str, status: int, kind: str) -> None:
        self.db.execute("INSERT INTO ai_errors (email, model, status, kind, at) VALUES (?,?,?,?,?)",
                        (email.lower(), model, status, kind[:80], time.time()))

    def ai_errors_since(self, since: float) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT email, model, status, kind, at FROM ai_errors WHERE at >= ? ORDER BY at", (since,))]

    def add_events(self, email: str, events: list[tuple[str, str, float]]) -> None:
        """events：[(name, day, at)]，按 (人, 功能, 天) 累计次数。"""
        e = email.lower()
        with self.lock:
            self.db.executemany(
                "INSERT INTO events VALUES (?, ?, ?, 1, ?, ?) ON CONFLICT(email, name, day) DO UPDATE SET "
                "n = n + 1, first_at = MIN(first_at, excluded.first_at), last_at = MAX(last_at, excluded.last_at)",
                [(e, n, d, t, t) for n, d, t in events])

    def touch_day(self, email: str, day: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO active_days VALUES (?, ?)", (email.lower(), day))

    # ---------- 隐私：同意、导出、彻底删除 ----------

    def set_analytics(self, email: str, on: bool) -> None:
        """隐私 v2 的「行为数据」开关。关掉时记下时间（清理任务据此删已采集的行为数据）。"""
        self.db.execute("UPDATE users SET analytics_off=? WHERE email=?",
                        (None if on else time.time(), email.lower()))

    def analytics_off_users(self) -> list[User]:
        return [self._user(r) for r in self.db.execute(
            "SELECT * FROM users WHERE analytics_off IS NOT NULL ORDER BY analytics_off")]

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
                "feedback": q("SELECT message, page, lang, user_agent, at FROM feedback WHERE email=? ORDER BY id"),
                "credit_requests": q("SELECT message, status, amount_usd, at, decided_at FROM credit_requests "
                                     "WHERE email=? ORDER BY id"),
                "events": q("SELECT name, day, n FROM events WHERE email=? ORDER BY day, name"),
                "location": q("SELECT ip, country, region, city, at FROM geo WHERE email=?"),
                "mail": q("SELECT kind, status, created_at, sent_at FROM mail_queue WHERE to_email=? ORDER BY id"),
                "active_days": [r["day"] for r in q("SELECT day FROM active_days WHERE email=? ORDER BY day")]}

    def delete_user(self, email: str) -> None:
        """彻底删除：账户、邀请、额度流水、用量、反馈一并删掉。机器与卷由调用方先销毁。"""
        e = email.lower()
        with self.lock:
            for t in ("usage", "ai_errors", "events", "active_days", "credit_requests", "grants", "feedback", "invites", "waitlist", "geo", "users"):
                self.db.execute(f"DELETE FROM {t} WHERE email=?", (e,))
            self.db.execute("DELETE FROM mail_queue WHERE to_email=?", (e,))
