"""管理命令（在网关 machine 上跑：fly ssh console -a joblander-gw -C "python -m gw.cli ..."）

  invite <email>...            加进邀请名单（同时从被拦名单移除）
  uninvite <email>...          移出邀请名单（已开通的账户不受影响；要删账户用 reset 或用户自己删除）
  blocked                      没被邀请就来登录、被拦下的人（首次被拦会邮件通知管理员）
  dismiss <email>...           从被拦名单里清掉（不认识的人）
  grant <email> <usd> [原因]   给额度（充值落地前，手工给朋友加额度也走这里）
  users                        列出用户、状态、余额
  upgrade <image>              把全部用户 machine 换到新镜像（数据在卷上，不受影响）
  feedback [n]                 最近 n 条用户反馈（默认 20）
  reset <email>                销毁该用户的 machine 与卷（数据不可恢复），下次登录按新用户重新开通
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
    elif cmd == "uninvite":
        for e in args:
            print(f"{e}: {'已移出' if store.uninvite(e) else '本来就不在邀请名单'}"
                  f"{'（账户仍在）' if store.get(e) else ''}")
    elif cmd == "blocked":
        import time as _t
        rows = store.waitlist()
        for w in rows:
            print(f"{w['email']:36} {w['attempts']:3} 次  首次 {_t.strftime('%m-%d %H:%M', _t.localtime(w['first_at']))}"
                  f"  最近 {_t.strftime('%m-%d %H:%M', _t.localtime(w['last_at']))}  [{w['lang'] or '-'}]")
        print(f"共 {len(rows)} 人" if rows else "没有被拦的人")
    elif cmd == "dismiss":
        for e in args:
            print(f"{e}: {'已清掉' if store.dismiss(e) else '不在被拦名单'}")
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
    elif cmd == "feedback":
        for f in store.list_feedback(int(args[0]) if args else 20):
            import time as _t
            print(f"#{f['id']} {_t.strftime('%m-%d %H:%M', _t.localtime(f['at']))} {f['email']} "
                  f"[{f['lang']}] {f['page']} {'✉' if f['emailed'] else '·'}\n    {f['message'][:300]}")
    elif cmd == "reset":
        asyncio.run(_reset(store, args[0]))
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



async def _reset(store: Store, email: str) -> None:
    u = store.get(email)
    if u is None:
        raise SystemExit(f"{email} 不存在")
    fly = Fly(os.environ["FLY_API_TOKEN"], os.environ.get("USER_APP", "joblander-users"),
              os.environ.get("FLY_REGION", "sin"))
    if u.machine_id:
        await fly.destroy_machine(u.machine_id)
    if u.volume_id:
        await fly.delete_volume(u.volume_id)
    store.clear_machine(email)
    print(f"{email}: 已重置，下次登录重新开通（额度保留 ${store.get(email).balance_usd:.2f}）")


if __name__ == "__main__":
    main(sys.argv[1:])
