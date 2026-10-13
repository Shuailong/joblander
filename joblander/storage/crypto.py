"""信封加密：每个账户一把数据密钥（DEK），由主密钥（KEK）包裹后存库。

- 生产：KEK 在 Cloud KMS，不导出、自动轮换；引擎只在内存里短暂持有解包后的 DEK（缓存 10 分钟）。
- 本机 / 测试：KEK 来自 JOBLANDER_KEK（base64 的 32 字节），或测试里直接给。

内容用 AES-256-GCM 加密，附加数据绑定「账户 ID + 文件 ID」：把别的账户、别的文件的密文搬过来，
解密直接失败——行级安全之外的第二道防线。
"""

from __future__ import annotations

import base64
import os
import threading
import time
from typing import Callable, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE = 12


class DecryptError(RuntimeError):
    """密文与账户 / 文件对不上（或被篡改）。正常运行中永远不该出现：出现即隔离违规。"""


class Kek(Protocol):
    id: str

    def wrap(self, dek: bytes) -> bytes: ...
    def unwrap(self, wrapped: bytes) -> bytes: ...


class LocalKek:
    def __init__(self, key: bytes | None = None, key_id: str = "local"):
        if key is None:
            raw = os.environ.get("JOBLANDER_KEK", "")
            if not raw:
                raise RuntimeError("缺 JOBLANDER_KEK（base64 编码的 32 字节主密钥）")
            key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError("主密钥必须是 32 字节")
        self._aead = AESGCM(key)
        self.id = key_id

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(NONCE)
        return nonce + self._aead.encrypt(nonce, dek, b"joblander-dek")

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            return self._aead.decrypt(wrapped[:NONCE], wrapped[NONCE:], b"joblander-dek")
        except InvalidTag as e:
            raise DecryptError("数据密钥解包失败") from e


class KmsKek:
    def __init__(self, key_name: str):
        self.id = key_name

    def wrap(self, dek: bytes) -> bytes:
        from joblander import gcp
        return gcp.kms_encrypt(self.id, dek)

    def unwrap(self, wrapped: bytes) -> bytes:
        from joblander import gcp
        return gcp.kms_decrypt(self.id, wrapped)


def kek_from_env() -> Kek:
    name = os.environ.get("JOBLANDER_KMS_KEY", "")
    return KmsKek(name) if name else LocalKek()


class Keyring:
    """DEK 的进程内缓存。loader(tenant_id) 返回该账户包裹后的 DEK（从数据库读）。"""

    def __init__(self, kek: Kek, ttl: float = 600):
        self.kek = kek
        self.ttl = ttl
        self._cache: dict[str, tuple[AESGCM, float]] = {}
        self._lock = threading.Lock()

    def new_wrapped_dek(self) -> bytes:
        return self.kek.wrap(AESGCM.generate_key(bit_length=256))

    def aead(self, tenant_id: str, loader: Callable[[str], bytes]) -> AESGCM:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(tenant_id)
            if hit and hit[1] > now:
                return hit[0]
        aead = AESGCM(self.kek.unwrap(loader(tenant_id)))
        with self._lock:
            self._cache[tenant_id] = (aead, now + self.ttl)
        return aead

    def forget(self, tenant_id: str) -> None:
        with self._lock:
            self._cache.pop(tenant_id, None)


def _ad(tenant_id: str, file_id: str) -> bytes:
    return f"{tenant_id}|{file_id}".encode()


def seal(aead: AESGCM, tenant_id: str, file_id: str, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    return nonce + aead.encrypt(nonce, plaintext, _ad(tenant_id, file_id))


def unseal(aead: AESGCM, tenant_id: str, file_id: str, blob: bytes) -> bytes:
    try:
        return aead.decrypt(blob[:NONCE], blob[NONCE:], _ad(tenant_id, file_id))
    except InvalidTag as e:
        from joblander import isolation
        isolation.violation("decrypt", f"{tenant_id}|{file_id}")
        raise DecryptError("密文与账户或文件不匹配") from e
