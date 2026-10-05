"""Fly Machines API 的最小封装：给新用户开一块卷 + 一台常开 machine，或把全体升级到新镜像。

用户 machine 不挂任何 services：公网不可达，只有网关经私网 <id>.vm.<app>.internal 访问。
"""

from __future__ import annotations

import httpx

API = "https://api.machines.dev/v1"


class FlyError(RuntimeError):
    pass


class Fly:
    def __init__(self, token: str, app: str, region: str, client: httpx.AsyncClient | None = None):
        self.app = app
        self.region = region
        self.http = client or httpx.AsyncClient(timeout=60)
        # `fly tokens create` 发的是 "FlyV1 fm2_…" 形式，自带 scheme，原样放进头；老式 token 才补 Bearer
        auth = token if token.startswith("FlyV1 ") else f"Bearer {token}"
        self.headers = {"Authorization": auth}

    async def _call(self, method: str, path: str, **kw) -> dict:
        r = await self.http.request(method, f"{API}/apps/{self.app}{path}",
                                    headers=self.headers, **kw)
        if r.status_code >= 400:
            raise FlyError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    @staticmethod
    def machine_config(image: str, env: dict[str, str], volume_id: str, memory_mb: int) -> dict:
        return {
            "image": image,
            "env": env,
            "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": memory_mb},
            "mounts": [{"volume": volume_id, "path": "/data"}],
            "restart": {"policy": "always"},
        }

    async def create_volume(self, size_gb: int = 1) -> str:
        v = await self._call("POST", "/volumes", json={
            "name": "data", "region": self.region, "size_gb": size_gb, "encrypted": True})
        return v["id"]

    async def create_machine(self, name: str, config: dict) -> str:
        m = await self._call("POST", "/machines", json={
            "name": name, "region": self.region, "config": config})
        return m["id"]

    async def wait_started(self, machine_id: str, timeout_s: int = 60) -> None:
        await self._call("GET", f"/machines/{machine_id}/wait",
                         params={"state": "started", "timeout": timeout_s})

    async def get_machine(self, machine_id: str) -> dict:
        return await self._call("GET", f"/machines/{machine_id}")

    async def update_machine(self, machine_id: str, config: dict) -> None:
        await self._call("POST", f"/machines/{machine_id}", json={"config": config})

    async def destroy_machine(self, machine_id: str) -> None:
        try:
            await self._call("DELETE", f"/machines/{machine_id}", params={"force": "true"})
        except FlyError as e:
            if "404" not in str(e):          # 已经没了 = 目的达成
                raise

    async def delete_volume(self, volume_id: str, tries: int = 10) -> None:
        """machine 销毁是异步的：卷在完全解挂前删不掉，退避重试。"""
        import asyncio
        for i in range(tries):
            try:
                await self._call("DELETE", f"/volumes/{volume_id}")
                return
            except FlyError as e:
                if "404" in str(e):
                    return
                if i == tries - 1:
                    raise
                await asyncio.sleep(min(2 * (i + 1), 10))

    def address(self, machine_id: str) -> str:
        return f"{machine_id}.vm.{self.app}.internal"
