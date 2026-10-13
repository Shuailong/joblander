"""IP → 大致所在地（国家 / 省 / 城市 / 经纬度）：用镜像里自带的 DB-IP Lite 离线库查，不把 IP 发给任何第三方。

库文件在构建镜像时下载（python -m gw.geo fetch <路径>）；文件不在就只记 IP、不查地点，其余照常。
IP Geolocation by DB-IP（https://db-ip.com），CC BY 4.0。
"""

from __future__ import annotations

import ipaddress
import os
import sys

DEFAULT_PATH = "/app/geo.mmdb"


class Geo:
    def __init__(self, path: str = DEFAULT_PATH):
        try:
            import maxminddb
            self.db = maxminddb.open_database(path)
        except Exception:                                       # noqa: BLE001  没库 / 没装包：只记 IP
            self.db = None

    def lookup(self, ip: str) -> dict:
        """查不到（内网地址、库里没有、没库）就只回国家代码为空的结果。"""
        out = {"country": "", "country_name": "", "region": "", "city": "", "lat": None, "lon": None}
        try:
            if self.db is None or not ipaddress.ip_address(ip).is_global:
                return out
            r = self.db.get(ip) or {}
        except ValueError:
            return out
        c = r.get("country") or {}
        names = c.get("names") or {}
        loc = r.get("location") or {}
        out.update(country=c.get("iso_code") or "", country_name=names.get("zh-CN") or names.get("en") or "",
                   region=((r.get("subdivisions") or [{}])[0].get("names") or {}).get("en", ""),
                   city=((r.get("city") or {}).get("names") or {}).get("en", ""),
                   lat=loc.get("latitude"), lon=loc.get("longitude"))
        return out


def client_ip(request) -> str:
    """真实来源 IP。Fly：入口代理放在 Fly-Client-IP。GCP：负载均衡器在 X-Forwarded-For 末尾追加「客户端,负载均衡器」
    两段，前面可能是客户端自己写的（能伪造），所以取倒数第二个；GCP 下也不认 Fly-Client-IP（没人替我们覆盖它）。
    本地 / 测试退回连接地址。"""
    if os.environ.get("GW_MODE") == "gcp":
        hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        ip = hops[-2] if len(hops) >= 2 else ""
    else:
        ip = (request.headers.get("fly-client-ip") or "").strip()
    if not ip and request.client:
        ip = request.client.host
    return ip[:64]


def mask_ip(ip: str | None) -> str:
    """后台里打码显示：IPv4 留前三段（1.2.3.x），IPv6 留前三组。"""
    if not ip:
        return "—"
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "—"
    if a.version == 4:
        return ".".join(ip.split(".")[:3]) + ".x"
    return ":".join(a.exploded.split(":")[:3]) + "::x"


def fetch(path: str) -> None:
    """下载当月（不行就上月）的 DB-IP City Lite 库。构建镜像时跑一次。"""
    import datetime
    import gzip
    import shutil
    import urllib.request
    d = datetime.date.today().replace(day=1)
    for month in (d, (d - datetime.timedelta(days=1)).replace(day=1)):
        url = f"https://download.db-ip.com/free/dbip-city-lite-{month:%Y-%m}.mmdb.gz"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})   # 默认的 Python UA 会被 403
            with urllib.request.urlopen(req, timeout=120) as r, gzip.GzipFile(fileobj=r) as g, open(path, "wb") as f:
                shutil.copyfileobj(g, f)
            print(f"geo: {url} → {path}")
            return
        except Exception as e:                                  # noqa: BLE001
            print(f"geo: {url} 下载失败：{e}")
    raise SystemExit("geo: 拿不到 IP 库")


if __name__ == "__main__" and sys.argv[1:2] == ["fetch"]:
    fetch(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PATH)
