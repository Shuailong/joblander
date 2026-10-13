"""Google Cloud 的最小 REST 客户端：只用标准库，不引入 google-cloud-* 那一大套依赖。

凭据一律来自运行环境的元数据服务器（Cloud Run 上即服务账号），代码与镜像里不放任何密钥。
本机与测试里不在 GCP 上：id_token() 返回空串，其余调用直接报错——测试用假实现替换。
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

METADATA = "http://metadata.google.internal/computeMetadata/v1"
_lock = threading.Lock()
_access: dict = {}                     # {"token": str, "exp": float}
_ids: dict[str, tuple[str, float]] = {}


class GcpError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


def on_gcp() -> bool:
    return bool(os.environ.get("K_SERVICE") or os.environ.get("JOBLANDER_ON_GCP"))


def _metadata(path: str, params: dict | None = None, timeout: float = 3) -> str:
    url = f"{METADATA}/{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def access_token() -> str:
    with _lock:
        if _access and _access["exp"] > time.time() + 60:
            return _access["token"]
    data = json.loads(_metadata("instance/service-accounts/default/token"))
    with _lock:
        _access.update(token=data["access_token"], exp=time.time() + int(data.get("expires_in", 300)))
        return _access["token"]


def id_token(audience: str) -> str:
    """调其他 Cloud Run 服务用的 ID 令牌（按受众缓存 50 分钟）；不在 GCP 上返回空串。"""
    if not on_gcp():
        return ""
    with _lock:
        hit = _ids.get(audience)
        if hit and hit[1] > time.time():
            return hit[0]
    token = _metadata("instance/service-accounts/default/identity",
                      {"audience": audience, "format": "full"})
    with _lock:
        _ids[audience] = (token, time.time() + 50 * 60)
    return token


def project_id() -> str:
    return os.environ.get("GOOGLE_CLOUD_PROJECT") or _metadata("project/project-id")


def _request(method: str, url: str, body: bytes | dict | None = None,
             content_type: str = "application/json", timeout: float = 30) -> bytes:
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {access_token()}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise GcpError(e.code, e.read().decode(errors="replace")[:300]) from e


# ---------- Cloud Storage ----------

def gcs_upload(bucket: str, name: str, data: bytes) -> None:
    q = urllib.parse.urlencode({"uploadType": "media", "name": name})
    _request("POST", f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?{q}",
             data, content_type="application/octet-stream", timeout=120)


def gcs_download(bucket: str, name: str) -> bytes:
    obj = urllib.parse.quote(name, safe="")
    return _request("GET", f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{obj}?alt=media",
                    timeout=120)


def gcs_delete(bucket: str, name: str) -> None:
    obj = urllib.parse.quote(name, safe="")
    try:
        _request("DELETE", f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{obj}")
    except GcpError as e:
        if e.status != 404:
            raise


def gcs_list(bucket: str, prefix: str) -> list[str]:
    names: list[str] = []
    token = ""
    while True:
        q = {"prefix": prefix, "fields": "items(name),nextPageToken"}
        if token:
            q["pageToken"] = token
        page = json.loads(_request(
            "GET", f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?{urllib.parse.urlencode(q)}"))
        names += [o["name"] for o in page.get("items", [])]
        token = page.get("nextPageToken", "")
        if not token:
            return names


# ---------- Cloud KMS ----------

def kms_encrypt(key_name: str, plaintext: bytes) -> bytes:
    out = json.loads(_request("POST", f"https://cloudkms.googleapis.com/v1/{key_name}:encrypt",
                              {"plaintext": base64.b64encode(plaintext).decode()}))
    return base64.b64decode(out["ciphertext"])


def kms_decrypt(key_name: str, ciphertext: bytes) -> bytes:
    out = json.loads(_request("POST", f"https://cloudkms.googleapis.com/v1/{key_name}:decrypt",
                              {"ciphertext": base64.b64encode(ciphertext).decode()}))
    return base64.b64decode(out["plaintext"])


# ---------- Cloud Tasks ----------

def tasks_create(queue: str, url: str, payload: dict, *, audience: str, service_account: str,
                 name: str = "", deadline_s: int = 1800) -> bool:
    """建一个 HTTP 任务（带 OIDC 令牌调回本服务）。name 相同的任务只建一次：返回 False 表示已存在。"""
    task: dict = {"httpRequest": {
        "httpMethod": "POST", "url": url,
        "headers": {"Content-Type": "application/json"},
        "body": base64.b64encode(json.dumps(payload).encode()).decode(),
        "oidcToken": {"serviceAccountEmail": service_account, "audience": audience}},
        "dispatchDeadline": f"{deadline_s}s"}
    if name:
        task["name"] = f"{queue}/tasks/{name}"
    try:
        _request("POST", f"https://cloudtasks.googleapis.com/v2/{queue}/tasks", {"task": task})
    except GcpError as e:
        if e.status == 409:            # 同名任务已存在（含刚执行完的去重窗口内）
            return False
        raise
    return True


# ---------- Pub/Sub ----------

def pubsub_publish(topic: str, messages: list[dict]) -> None:
    body = {"messages": [{"data": base64.b64encode(json.dumps(m, ensure_ascii=False).encode()).decode()}
                         for m in messages]}
    _request("POST", f"https://pubsub.googleapis.com/v1/{topic}:publish", body)
