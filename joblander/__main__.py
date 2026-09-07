"""joblander CLI（P0）。

用法：
  python -m joblander pull                     # 拉 tracker → 投影 + 事件
  python -m joblander brief <公司> [--note X]  # 生成面前 brief（W7）
  python -m joblander check "<文本>"           # Sentinel 口径检查
  python -m joblander scribe <转写文件> <公司> # W8 影子：产提案文件，不写 SoT
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：可预期的配置/凭证问题打成一行人话，不甩栈给用户
    （未预期的异常照旧抛出——那是 bug，栈有用）。"""
    from joblander.config import ConfigError
    from joblander.llm import LLMError
    from joblander.notion import NotionError
    try:
        return _run(argv)
    except (ConfigError, LLMError, NotionError, FileNotFoundError, ValueError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="joblander")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pull")

    p_brief = sub.add_parser("brief")
    p_brief.add_argument("company")
    p_brief.add_argument("--note", default="", help="本场特别注意（人工补充）")
    p_brief.add_argument("--round", default="", dest="round_type",
                         help="轮次类型（screening/oa/tech/hm/bar/negotiation）")

    p_check = sub.add_parser("check")
    p_check.add_argument("text")
    p_check.add_argument("--deep", action="store_true", help="附加 LLM 判断层")

    p_scribe = sub.add_parser("scribe")
    p_scribe.add_argument("transcript")
    p_scribe.add_argument("company")

    sub.add_parser("daily")

    p_intake = sub.add_parser("intake")
    p_intake.add_argument("file", help="贴入内容的文本文件（- 读 stdin）")
    p_intake.add_argument("--source", default="paste")

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("proposal", help="11-shadow / 12-intake 下的提案 JSON")
    p_apply.add_argument("--yes", action="store_true", help="实弹执行（缺省 dry-run）")

    p_res = sub.add_parser("research", help="尽调：无参数=零输入自主检索；给 URL/文件=喂入种子后补缺")
    p_res.add_argument("company")
    p_res.add_argument("--url", action="append", default=[], help="喂入公开页面 URL（可多个）")
    p_res.add_argument("--file", action="append", default=[], help="喂入本地材料文件（可多个）")

    p_weekly = sub.add_parser("weekly")
    p_weekly.add_argument("--no-llm", action="store_true")

    p_offers = sub.add_parser("offers")
    p_offers.add_argument("file", help="offers JSON：[{name, base_monthly, ...}]")

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--deep", action="store_true", help="附加 LLM 判断层")

    p_ref = sub.add_parser("referral")
    p_ref.add_argument("company")

    sub.add_parser("onboard")

    p_gauth = sub.add_parser("gmail-auth")
    p_gauth.add_argument("--code", help="第二步：粘贴授权 code")
    p_gscan = sub.add_parser("gmail-scan")
    p_gscan.add_argument("--days", type=int, default=3)

    p_web = sub.add_parser("web")
    p_web.add_argument("--port", type=int, default=8899)
    p_web.add_argument("--no-daemon", action="store_true")

    sub.add_parser("daemon")

    p_cauth = sub.add_parser("cal-auth")
    p_cauth.add_argument("--write", action="store_true")
    p_cauth.add_argument("--code")
    p_cev = sub.add_parser("cal-events")
    p_cev.add_argument("--days", type=int, default=10)
    p_ccr = sub.add_parser("cal-create")
    p_ccr.add_argument("title"); p_ccr.add_argument("start"); p_ccr.add_argument("end")
    p_ccr.add_argument("--desc", default=""); p_ccr.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)

    from joblander.config import load_config
    cfg = load_config()

    if args.cmd == "pull":
        from joblander.notion import pull_tracker
        rows = pull_tracker(cfg)
        print(f"pulled {len(rows)} rows → 09-projections/tracker.json")

    elif args.cmd == "brief":
        from joblander.llm import from_config as llm_from_config
        from joblander.prep import build_brief
        out, _ = build_brief(cfg, llm_from_config(cfg), args.company,
                             round_note=args.note, round_type=args.round_type)
        print(f"brief → {out}")

    elif args.cmd == "check":
        from joblander.sentinel import Sentinel
        print(Sentinel.from_config(cfg).check(args.text).explain())
        if args.deep:
            from joblander.judge import judge
            from joblander.llm import from_config as llm_from_config
            for f in judge(cfg, llm_from_config(cfg, "flash"), args.text):
                mark = "⚠️" if f.get("verdict") == "attention" else "·"
                print(f"{mark} {f.get('check')}：{f.get('note')}")

    elif args.cmd == "daily":
        from joblander.daily import build_daily
        from joblander.notion import NotionClient
        from joblander.notion import notion_configured
        client = NotionClient(cfg.raw["notion"]["token"]) if notion_configured(cfg) else None
        out, _ = build_daily(cfg, notion_client=client)
        print(f"晨报 → {out}")

    elif args.cmd == "intake":
        import sys as _sys
        from joblander.llm import from_config as llm_from_config
        from joblander.scout import intake
        text = _sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        out = intake(cfg, llm_from_config(cfg, "flash"), text, source_hint=args.source)
        print(f"intake 提案 → {out}" if out else "噪音闸：无公司无岗位，未入队（见 event log）")

    elif args.cmd == "apply":
        import json as _json
        from joblander.applyops import apply_proposal
        result = apply_proposal(cfg, args.proposal, yes=args.yes)
        print(_json.dumps(result, ensure_ascii=False)[:600])
        print("✅ 已执行并标记 approved" if args.yes else "（dry-run；加 --yes 实弹执行）")

    elif args.cmd == "web":
        import uvicorn
        from joblander.web.app import create_app
        uvicorn.run(create_app(with_daemon=not args.no_daemon),
                    host="127.0.0.1", port=args.port)

    elif args.cmd == "daemon":
        from joblander.daemon import Daemon
        Daemon(cfg).run_forever()

    elif args.cmd == "scribe":
        from joblander.llm import from_config as llm_from_config
        from joblander.prep import _load_projection, find_row
        from joblander.scribe import shadow_run
        row = find_row(_load_projection(cfg), args.company)
        out = shadow_run(cfg, llm_from_config(cfg), args.transcript, row)
        print(f"shadow proposal → {out}")

    elif args.cmd == "research":
        from joblander.llm import from_config as llm_from_config
        from joblander.researcher import diligence
        materials = [{"label": f, "text": open(f, encoding="utf-8", errors="replace").read()}
                     for f in args.file]
        d = diligence(cfg, llm_from_config(cfg), args.company,
                      seed_urls=args.url, seed_materials=materials)
        seeded = d.get("seeded") or {}
        fed = len(seeded.get("urls", [])) + len(seeded.get("materials", []))
        print(f"dossier → {len(d.get('facts', []))} 条事实 · {len(d.get('sources', []))} 个来源"
              + (f"（喂入 {fed} 份）" if fed else "（零输入尽调）"))

    elif args.cmd == "weekly":
        from joblander.weekly import build_weekly
        llm = None
        if not args.no_llm:
            from joblander.llm import from_config as llm_from_config
            llm = llm_from_config(cfg)
        out, _ = build_weekly(cfg, llm=llm)
        print(f"周报 → {out}")

    elif args.cmd == "offers":
        import json as _json
        from joblander.offer import build_offer_matrix
        offers = _json.loads(open(args.file, encoding="utf-8").read())
        out = build_offer_matrix(cfg, offers)
        print(f"对比矩阵 → {out}")

    elif args.cmd == "audit":
        from joblander.consistency import audit_materials
        llm = None
        if args.deep:
            from joblander.llm import from_config as llm_from_config
            llm = llm_from_config(cfg)
        out, _ = audit_materials(cfg, llm=llm)
        print(f"巡检报告 → {out}")

    elif args.cmd == "referral":
        import json as _json
        from joblander.llm import from_config as llm_from_config
        from joblander.referral import suggest_referral
        print(_json.dumps(suggest_referral(cfg, llm_from_config(cfg), args.company),
                          ensure_ascii=False, indent=1))

    elif args.cmd == "onboard":
        from joblander.onboard import onboard
        print(onboard(cfg))

    elif args.cmd == "gmail-auth":
        from joblander import gmail_sync
        if args.code:
            print(f"token → {gmail_sync.exchange_code(cfg, args.code)}")
        else:
            print(gmail_sync.auth_url(cfg), flush=True)
            code = gmail_sync.wait_for_code()          # 本地回环自动接 code
            print(f"token → {gmail_sync.exchange_code(cfg, code)}")

    elif args.cmd == "gmail-scan":
        from joblander import gmail_sync
        from joblander.llm import from_config as llm_from_config
        outs = gmail_sync.scan(cfg, llm_from_config(cfg, "flash"), days=args.days)
        print(f"{len(outs)} 条 intake 提案" + ("：" if outs else ""))
        for o in outs:
            print(f"  {o}")

    elif args.cmd == "cal-auth":
        from joblander import calendar_sync
        if args.code:
            print(f"token → {calendar_sync.exchange_code(cfg, args.code)}")
        else:
            # 旧的 cal-auth 走 OOB（urn:ietf:wg:oauth:2.0:oob），Google 2022 年就封了，
            # 打印出来的 URL 必然 invalid_request。gmail-auth 的 loopback 流一次授权
            # 已经把日历读写 scope 一起拿了，并写同一份 calendar_token.json。
            print("✗ cal-auth 的 OOB 授权已被 Google 停用。改跑 `joblander gmail-auth`——"
                  "同一次授权已包含日历读写权限，token 落 "
                  ".credentials/calendar_token.json", file=sys.stderr)
            return 1

    elif args.cmd == "cal-events":
        import json as _json
        from joblander import calendar_sync
        for ev in calendar_sync.upcoming_events(cfg, days=args.days):
            print(_json.dumps(ev, ensure_ascii=False))

    elif args.cmd == "cal-create":
        import json as _json
        from joblander import calendar_sync
        r = calendar_sync.create_event(cfg, args.title, args.start, args.end,
                                       description=args.desc, confirmed=args.yes)
        print(_json.dumps(r, ensure_ascii=False, indent=1))

    return 0


if __name__ == "__main__":
    sys.exit(main())
