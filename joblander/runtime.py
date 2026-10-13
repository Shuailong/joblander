"""运行形态 —— 同一份引擎代码跑在三种地方：

- local：本机单用户（开源版）。数据在本地文件夹，调度器与后台任务都在进程内。
- fly：云端旧形态，每个用户一台 Fly 机器 + 独占磁盘。本质仍是单用户，只是前面多了登录网关，
  靠 JOBLANDER_GATEWAY_TOKEN 识别。
- multi：GCP 多租户形态。所有账户共享一组 Cloud Run 服务，数据按账户隔离在 Postgres
  （行级安全）与 Cloud Storage 里并各自加密；当前账户由网关签发的令牌决定（见 tenancy.py）。
  用 JOBLANDER_MODE=multi 开启。
"""

from __future__ import annotations

import os
import urllib.parse


def mode() -> str:
    if os.environ.get("JOBLANDER_MODE") == "multi":
        return "multi"
    if os.environ.get("JOBLANDER_GATEWAY_TOKEN"):
        return "fly"
    return "local"


def is_multi() -> bool:
    return mode() == "multi"


def is_cloud() -> bool:
    """有登录网关在前面（fly 或 multi）：界面要显示账户入口、额度提示等。"""
    return mode() != "local"


def audience_of(url: str) -> str:
    """Cloud Run 的 ID 令牌受众是服务根地址（scheme://host），不含路径。"""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def upstream_headers(url: str) -> dict[str, str]:
    """调计量服务（OpenAI 兼容代理 / 搜索代理 / 用量上报）时要带的头。

    fly：每台机器的计量子 key 放在 Authorization（OPENAI_API_KEY）。
    multi：Authorization 留给 OpenAI 兼容协议本身（填占位）；服务间鉴权走 Cloud Run 认的
    X-Serverless-Authorization（本服务的 ID 令牌）；账户由 X-Joblander-Tenant 指明——计量服务只接受
    引擎与任务服务的调用（IAM），所以这个头可信。"""
    if not is_multi():
        return {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"}
    from joblander import gcp
    from joblander.tenancy import tenant_id
    headers = {"Authorization": "Bearer meter", "X-Joblander-Tenant": tenant_id()}
    token = gcp.id_token(audience_of(url))
    if token:
        headers["X-Serverless-Authorization"] = f"Bearer {token}"
    return headers
