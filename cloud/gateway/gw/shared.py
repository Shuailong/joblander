"""GCP 形态：所有账户共享一组引擎服务（见仓库 joblander/cloud/ 与技术方案「目标架构」）。

网关里原来跟 Fly 打交道的地方（开卷、开机器、转发地址、休眠）都经过一个「后端」对象。
SharedEngine 提供同样的接口，背后换成：
- 开通 = 让任务服务建一个账户（POST /_internal/tenants），users.volume_id 存账户 ID；
- 删除 / 重置 = 让任务服务删掉这个账户的全部数据；
- 转发 = 发往引擎服务，带上本账户的短期令牌（引擎只认令牌里的账户）与本服务的 ID 令牌（Cloud Run IAM）；
- 没有机器可睡：状态永远是 started。

另有 PgLeader：多个网关实例时，只让一个实例跑后台循环（发信队列、每日汇总）。
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import urllib.parse

import httpx

from gw.store import User


def _b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def tenant_token(tenant_id: str, secret: str, ttl: int = 300, now: float | None = None) -> str:
    """与引擎 joblander/cloud/tokens.py 同一格式（HS256 JWT）。两边各自实现，避免网关依赖引擎包。"""
    import hashlib
    import hmac
    import json
    now = time.time() if now is None else now
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"sub": tenant_id, "aud": "engine", "iat": int(now), "exp": int(now + ttl)},
                           separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


class IdTokens:
    """调其他 Cloud Run 服务用的 ID 令牌（元数据服务器签发，按受众缓存 50 分钟）。不在 GCP 上返回空串。"""

    def __init__(self, client: httpx.AsyncClient):
        self.http = client
        self._cache: dict[str, tuple[str, float]] = {}

    async def get(self, audience: str) -> str:
        if not os.environ.get("K_SERVICE"):
            return ""
        hit = self._cache.get(audience)
        if hit and hit[1] > time.time():
            return hit[0]
        r = await self.http.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity",
            params={"audience": audience, "format": "full"}, headers={"Metadata-Flavor": "Google"}, timeout=5)
        r.raise_for_status()
        self._cache[audience] = (r.text, time.time() + 50 * 60)
        return r.text


class SharedEngine:
    """与 gw.flyapi.Fly 同一组方法，供 web.py / sleep.py 原样调用。"""

    routes_by_host = True       # 转发时保留 Host（Cloud Run 按它路由），对外域名放 X-Forwarded-Host

    def __init__(self, engine_url: str, worker_url: str, token_secret: str,
                 client: httpx.AsyncClient | None = None):
        self.engine_url = engine_url.rstrip("/")
        self.worker_url = worker_url.rstrip("/")
        self.secret = token_secret
        self.http = client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
        self.ids = IdTokens(self.http)

    async def _worker(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {}
        token = await self.ids.get(self.worker_url)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = await self.http.request(method, self.worker_url + path, headers=headers, **kw)
        r.raise_for_status()
        return r

    # ---------- 与 Fly 同名的开通 / 删除接口 ----------

    async def create_volume(self, size_gb: int = 1) -> str:
        """「卷」在共享形态下就是账户：这里只生成账户 ID，真正开通在 create_machine。"""
        return "t" + secrets.token_hex(10)

    @staticmethod
    def machine_config(image: str, env: dict[str, str], volume_id: str, memory_mb: int) -> dict:
        return {"tenant_id": volume_id, "lang": env.get("JOBLANDER_LANG")}

    async def create_machine(self, name: str, config: dict) -> str:
        body = {"tenant_id": config["tenant_id"]}
        if config.get("lang") in ("zh", "en"):
            body["lang"] = config["lang"]
        await self._worker("POST", "/_internal/tenants", json=body)
        return "shared"

    async def wait_started(self, machine_id: str, timeout_s: int = 60) -> None:
        return None

    async def destroy_machine(self, machine_id: str) -> None:
        return None

    async def delete_volume(self, volume_id: str, tries: int = 10) -> None:
        """删账户：引擎库里的文件、任务、数据密钥与存储桶里的大文件一并删除。"""
        await self._worker("DELETE", f"/_internal/tenants/{urllib.parse.quote(volume_id)}")

    async def machine_state(self, machine_id: str) -> str:
        return "started"

    async def start_machine(self, machine_id: str) -> None:
        return None

    async def suspend_machine(self, machine_id: str) -> None:
        return None

    async def stop_machine(self, machine_id: str) -> None:
        return None

    # ---------- 转发 ----------

    def url_for(self, user: User, path: str) -> str:
        return f"{self.engine_url}/{path}"

    async def auth_headers(self, user: User) -> dict[str, str]:
        headers = {"x-joblander-tenant-token": tenant_token(user.volume_id or "", self.secret)}
        token = await self.ids.get(self.engine_url)
        if token:
            headers["x-serverless-authorization"] = f"Bearer {token}"
        return headers

    def address(self, machine_id: str) -> str:            # 休眠探活用；共享形态不休眠
        return urllib.parse.urlsplit(self.engine_url).netloc


class PgLeader:
    """持有一把会话级咨询锁的实例才跑后台循环；实例没了锁自动释放，别的实例下一轮接手。"""

    KEY = 7_402_118_337            # 任意固定数：网关后台循环

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None
        self._lock = threading.Lock()

    def ok(self) -> bool:
        import psycopg
        with self._lock:
            try:
                if self._conn is not None and not self._conn.closed:
                    self._conn.execute("SELECT 1")
                    return True
                self._conn = psycopg.connect(self.dsn, autocommit=True)
                got = self._conn.execute("SELECT pg_try_advisory_lock(%s)", (self.KEY,)).fetchone()[0]
                if not got:
                    self._conn.close()
                    self._conn = None
                return bool(got)
            except Exception:                                  # noqa: BLE001  连不上就当不是领头的
                self._conn = None
                return False
