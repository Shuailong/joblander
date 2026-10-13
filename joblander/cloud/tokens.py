"""账户令牌：网关签发、引擎验证，说明「这个请求属于哪个账户」。

格式是 HS256 的 JWT（不引第三方库），有效期 5 分钟，网关每次转发现签。密钥放 Secret Manager，
网关与引擎各读一份（JOBLANDER_TENANT_TOKEN_SECRET）。引擎只认令牌里的账户，请求参数里的
账户 ID 一律不认（安全 · 租户数据隔离第 1 层）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{5,63}$")
TTL = 300


class TokenError(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def secret() -> bytes:
    s = os.environ.get("JOBLANDER_TENANT_TOKEN_SECRET", "")
    if len(s) < 32:
        raise TokenError("缺 JOBLANDER_TENANT_TOKEN_SECRET（至少 32 个字符）")
    return s.encode()


def sign(tenant_id: str, *, key: bytes | None = None, ttl: int = TTL, aud: str = "engine",
         now: float | None = None) -> str:
    if not TENANT_RE.match(tenant_id):
        raise TokenError(f"账户 ID 格式不对：{tenant_id!r}")
    now = time.time() if now is None else now
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"sub": tenant_id, "aud": aud, "iat": int(now), "exp": int(now + ttl)},
                           separators=(",", ":")).encode())
    sig = hmac.new(key or secret(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def verify(token: str, *, key: bytes | None = None, aud: str = "engine", now: float | None = None) -> str:
    """返回令牌里的账户 ID；签名、受众、过期、格式任一不对都抛 TokenError。"""
    try:
        header, body, sig = token.split(".")
        if json.loads(_unb64(header)).get("alg") != "HS256":
            raise TokenError("算法不对")
        want = hmac.new(key or secret(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(sig)):
            raise TokenError("签名不对")
        claims = json.loads(_unb64(body))
    except TokenError:
        raise
    except Exception as e:
        raise TokenError("令牌无法解析") from e
    now = time.time() if now is None else now
    if claims.get("aud") != aud:
        raise TokenError("受众不对")
    if not isinstance(claims.get("exp"), int) or claims["exp"] < now:
        raise TokenError("令牌已过期")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not TENANT_RE.match(sub):
        raise TokenError("账户 ID 格式不对")
    return sub


def new_tenant_id() -> str:
    """网关开通账户时生成：随机、与邮箱无关（引擎库里不出现邮箱）。"""
    return "t" + os.urandom(10).hex()
