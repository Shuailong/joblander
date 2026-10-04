"""管理命令（在网关 machine 上跑：fly ssh console -a joblander-gw -C "python -m gw.cli ..."）

  invite <email>...            加进邀请名单
  grant <email> <usd> [原因]   给额度（充值落地前，手工给朋友加额度也走这里）
  users                        列出用户、状态、余额
  upgrade <image>              把全部用户 machine 换到新镜像（数据在卷上，不受影响）
"""

from __future__ import annotations

import asyncio
import os
import sys

from gw.flyapi import Fly
from gw.store import Store


def main(argv: list[str]) -> None:
    store = Store(os.environ.get("GW_DB", "/data/gw.sqlite"))
    if not argv:
        print(__doc__); return
    cmd, *args = argv
    if cmd == "invite":
        for e in args:
            store.invite(e)
        print(f"已邀请 {len(args)} 人")
    elif cmd == "grant":
        email, usd, *reason = args
        if store.get(email) is None:
            raise SystemExit(f"{email} 还没登录过（先 invite，等对方登录后再 grant）")
        store.grant(email, float(usd), " ".join(reason) or "手工发放")
        u = store.get(email)
        print(f"{email} 余额 ${u.balance_usd:.2f}")
    elif cmd == "users":
        for u in store.all():
            print(f"{u.email:36} {u.status:12} {u.machine_id or '-':16} "
                  f"余额 ${u.balance_usd:7.2f}  已用 ${u.spent_usd:.2f}  {u.error or ''}")
    elif cmd == "upgrade":
        asyncio.run(_upgrade(store, args[0]))
    else:
        print(__doc__)


async def _upgrade(store: Store, image: str) -> None:
    fly = Fly(os.environ["FLY_API_TOKEN"], os.environ.get("USER_APP", "joblander-users"),
              os.environ.get("FLY_REGION", "sin"))
    for u in store.all():
        if not u.machine_id:
            continue
        cfg = (await fly.get_machine(u.machine_id))["config"]
        cfg["image"] = image
        # 新版本引入的环境变量补给老 machine（只补不改：口令与子 key 原样保留）
        meter = os.environ.get("METER_URL", "http://joblander-gw.internal:8081/v1")
        cfg.setdefault("env", {}).setdefault("JOBLANDER_SEARCH_URL", meter.rstrip("/") + "/search")
        await fly.update_machine(u.machine_id, cfg)
        print(f"{u.email}: → {image}")


if __name__ == "__main__":
    main(sys.argv[1:])
