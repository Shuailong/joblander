"""管理后台（/_gw/admin）：只给 ADMIN_EMAILS 看。用户、用量、名单、反馈一页看完，外加邀请 / 清掉 / 加额度。

只展示账户汇总与用量元数据（模型、token、花费、时间），看不到也不读任何用户空间里的内容。
"""

from __future__ import annotations

import html
import time
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

from gw import pages

DAYS = 30

_STATUS = {"ready": "就绪", "new": "未开通", "provisioning": "开通中", "failed": "开通失败", "deleting": "删除中"}

CSS = """
.adm{max-width:1180px;margin:0 auto;padding:28px 24px 60px}
.adm header{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.adm header img{width:30px;height:30px;border-radius:8px}
.adm header h1{font-size:20px;margin:0;font-weight:650;letter-spacing:-.01em;white-space:nowrap}
.adm header .tbtn{white-space:nowrap}
.adm header .sp{flex:1}
.adm header .when{color:var(--ink-3);font-size:12.5px}
.flash{background:var(--accent-soft);color:var(--accent-ink);border-radius:10px;padding:10px 14px;margin-bottom:18px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi b{display:block;font-size:24px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi span{color:var(--ink-3);font-size:12.5px}
.kpi.warn b{color:var(--red)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:18px;overflow-x:auto}
.card h2{font-size:14.5px;margin:0 0 12px;font-weight:620;display:flex;align-items:center;gap:8px}
.card h2 small{color:var(--ink-3);font-weight:450;font-size:12.5px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.grid2 .card{margin-bottom:0}
.adm table{font-size:13px}
.adm th{text-align:left;font-weight:550;color:var(--ink-3);font-size:12px;padding:0 10px 8px 0;border-bottom:1px solid var(--line);white-space:nowrap}
.adm td{padding:8px 10px 8px 0;vertical-align:middle}
.adm td.n,.adm th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.adm td.dim{color:var(--ink-3);white-space:nowrap}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2);white-space:nowrap}
.pill.ok{background:var(--accent-soft);border-color:transparent;color:var(--accent-ink)}
.pill.bad{color:var(--red)}
.low{color:var(--red);font-weight:600}
.adm form.inl{display:inline-flex;gap:6px;align-items:center;margin:0}
.adm input{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink)}
.adm input.usd{width:62px}
.adm .tbtn{height:28px}
.adm .tbtn.go{background:var(--accent);color:var(--on-accent);border-color:transparent}
.chart{display:flex;align-items:flex-end;gap:3px;height:120px;padding-top:6px}
.chart div{flex:1;background:var(--accent);opacity:.85;border-radius:3px 3px 0 0;min-height:1px}
.chart div.z{background:var(--line);opacity:1}
.axis{display:flex;justify-content:space-between;color:var(--ink-3);font-size:11.5px;margin-top:6px}
.fb{white-space:pre-wrap;max-width:560px}
.empty{color:var(--ink-3);font-size:13px}
@media (max-width:820px){.grid2{grid-template-columns:1fr}.adm{padding:18px 16px 40px}.adm header .when{display:none}}
"""


def _t(ts: float | None, tz: ZoneInfo, fmt: str = "%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(ts, tz).strftime(fmt) if ts else "—"


def _ago(ts: float | None, now: float) -> str:
    if not ts:
        return "从未"
    d = now - ts
    for unit, sec in (("天", 86400), ("小时", 3600), ("分钟", 60)):
        if d >= sec:
            return f"{int(d // sec)} {unit}前"
    return "刚刚"


def _usd(v: float) -> str:
    return f"-${-v:.2f}" if v < 0 else f"${v:.2f}"


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render(snap: dict, *, low_usd: float, tz_name: str, privacy_version: str, flash: str = "",
           now: float | None = None) -> HTMLResponse:
    now = now or time.time()
    tz = ZoneInfo(tz_name)
    users, usage = snap["users"], snap["usage"]
    day = 86400

    # ---- 汇总 ----
    active7 = {u["email"] for u in usage if u["at"] >= now - 7 * day}
    cost = lambda since: sum(u["cost_usd"] for u in usage if u["at"] >= since)          # noqa: E731
    today0 = datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    total_spent = sum(u["spent_usd"] for u in users)
    lows = [u for u in users if u["credit_usd"] - u["spent_usd"] < low_usd]
    kpis = [
        (len(users), "用户", ""),
        (len(active7), "7 天活跃", ""),
        (f"${cost(today0):.2f}", "今天花费", ""),
        (f"${cost(now - 7 * day):.2f}", "7 天花费", ""),
        (f"${total_spent:.2f}", "累计花费", ""),
        (len(snap["waitlist"]), "被拦待处理", "warn" if snap["waitlist"] else ""),
        (len(lows), f"余额 < ${low_usd:g}", "warn" if lows else ""),
    ]
    kpi_html = "".join(f'<div class="kpi {c}"><b>{v}</b><span>{label}</span></div>' for v, label, c in kpis)

    # ---- 30 天每日花费 ----
    per_day: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for u in usage:
        k = _t(u["at"], tz, "%Y-%m-%d")
        per_day[k][0] += u["cost_usd"]
        per_day[k][1] += 1
    days = [datetime.fromtimestamp(now - i * day, tz).strftime("%Y-%m-%d") for i in range(DAYS - 1, -1, -1)]
    top = max(per_day[d][0] for d in days)
    peak = top or 1
    bars = "".join(
        f'<div class="{"z" if not per_day[d][0] else ""}" style="height:{max(per_day[d][0] / peak * 100, 1):.1f}%" '
        f'title="{d}　${per_day[d][0]:.3f}　{per_day[d][1]} 次"></div>' for d in days)
    chart = (f'<div class="chart">{bars}</div><div class="axis"><span>{days[0][5:]}</span>'
             f'<span>单日最高 ${top:.2f}</span><span>{days[-1][5:]}</span></div>')

    # ---- 用户 ----
    calls7 = defaultdict(int)
    cost7 = defaultdict(float)
    for u in usage:
        if u["at"] >= now - 7 * day:
            calls7[u["email"]] += 1
            cost7[u["email"]] += u["cost_usd"]

    def user_row(u: dict) -> str:
        bal = u["credit_usd"] - u["spent_usd"]
        st = u["status"]
        pill = "ok" if st == "ready" else "bad" if st == "failed" else ""
        consent = ("✓" if u["privacy_version"] == privacy_version
                   else ("旧版" if u["privacy_version"] else "未同意"))
        err = f'<br><span class="dim" title="{_e(u["error"])}">{_e(u["error"])[:60]}</span>' if u["error"] else ""
        return (f'<tr><td>{_e(u["email"])}{err}</td>'
                f'<td><span class="pill {pill}">{_STATUS.get(st, _e(st))}</span></td>'
                f'<td class="dim">{_e(u["lang"] or "—")}</td>'
                f'<td class="dim">{_t(u["created_at"], tz)}</td>'
                f'<td class="dim" title="{_t(u["last_at"], tz)}">{_ago(u["last_at"], now)}</td>'
                f'<td class="n">{calls7[u["email"]]} / {u["calls"]}</td>'
                f'<td class="n">${cost7[u["email"]]:.2f} / ${u["spent_usd"]:.2f}</td>'
                f'<td class="n {"low" if bal < low_usd else ""}">{_usd(bal)}</td>'
                f'<td class="dim">{consent}</td>'
                f'<td><form class="inl" method="post" action="/_gw/admin/grant">'
                f'<input type="hidden" name="email" value="{_e(u["email"])}">'
                f'<input class="usd" name="usd" type="number" step="0.5" min="0.5" max="100" value="5" aria-label="美元">'
                f'<button class="tbtn">加额度</button></form></td></tr>')

    users_html = ('<table><tr><th>邮箱</th><th>机器</th><th>语言</th><th>注册</th><th>最近活跃</th>'
                  '<th class="n">调用 7天/累计</th><th class="n">花费 7天/累计</th><th class="n">余额</th>'
                  '<th>隐私同意</th><th></th></tr>' + "".join(user_row(u) for u in users) + '</table>'
                  if users else '<p class="empty">还没有用户</p>')

    # ---- 名单 ----
    def wl_row(w: dict) -> str:
        e = _e(w["email"])
        return (f'<tr><td>{e}</td><td class="n">{w["attempts"]} 次</td><td class="dim">{_t(w["last_at"], tz)}</td>'
                f'<td class="dim">{_e(w["lang"] or "—")}</td><td style="white-space:nowrap">'
                f'<form class="inl" method="post" action="/_gw/admin/invite"><input type="hidden" name="email" value="{e}">'
                f'<button class="tbtn go">邀请</button></form> '
                f'<form class="inl" method="post" action="/_gw/admin/dismiss"><input type="hidden" name="email" value="{e}">'
                f'<button class="tbtn">清掉</button></form></td></tr>')

    wl_html = ('<table>' + "".join(wl_row(w) for w in snap["waitlist"]) + '</table>'
               if snap["waitlist"] else '<p class="empty">没有被拦的人</p>')
    pend_html = ('<table>' + "".join(f'<tr><td>{_e(i["email"])}</td><td class="dim">邀请于 {_t(i["created_at"], tz)}</td></tr>'
                                     for i in snap["pending_invites"]) + '</table>'
                 if snap["pending_invites"] else '<p class="empty">邀请过的人都已登录</p>')
    invite_form = ('<form class="inl" method="post" action="/_gw/admin/invite" style="margin-bottom:12px">'
                   '<input name="email" type="email" required placeholder="name@gmail.com" style="width:230px">'
                   '<button class="tbtn go">邀请</button></form>')

    # ---- 按模型 ----
    by_model: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0.0])
    for u in usage:
        m = by_model[u["model"]]
        m[0] += 1; m[1] += u["prompt_tokens"]; m[2] += u["completion_tokens"]; m[3] += u["cost_usd"]
    model_html = ('<table><tr><th>模型</th><th class="n">调用</th><th class="n">输入 token</th>'
                  '<th class="n">输出 token</th><th class="n">花费</th></tr>' + "".join(
                      f'<tr><td>{_e(k)}</td><td class="n">{v[0]}</td><td class="n">{v[1]:,}</td>'
                      f'<td class="n">{v[2]:,}</td><td class="n">${v[3]:.3f}</td></tr>'
                      for k, v in sorted(by_model.items(), key=lambda kv: -kv[1][3])) + '</table>'
                  if by_model else f'<p class="empty">{DAYS} 天内没有调用</p>')

    # ---- 反馈 / 发放 ----
    fb_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(f["at"], tz)}</td><td>{_e(f["email"])}<br><span class="dim">{_e(f["page"])}</span></td>'
        f'<td class="fb">{_e(f["message"][:600])}</td><td class="dim">{"✉" if f["emailed"] else "·"}</td></tr>'
        for f in snap["feedback"]) + '</table>' if snap["feedback"] else '<p class="empty">还没有反馈</p>')
    gr_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(g["at"], tz)}</td><td>{_e(g["email"])}</td>'
        f'<td class="n">${g["amount_usd"]:.2f}</td><td class="dim">{_e(g["reason"])}</td></tr>'
        for g in snap["grants"]) + '</table>' if snap["grants"] else '<p class="empty">没有发放记录</p>')

    body = f"""<div class="adm">
<header><a href="/"><img src="{pages.LOGO}" alt=""></a><h1>后台</h1><span class="sp"></span>
<span class="when">{_t(now, tz, "%Y-%m-%d %H:%M")} {_e(tz_name)}</span>
<button class="tbtn" onclick="jlTheme()" title="切换深浅色">{pages.icon("moon", 15)}</button>
<a class="tbtn" href="/">返回</a></header>
{f'<div class="flash">{_e(flash)}</div>' if flash else ''}
<div class="kpis">{kpi_html}</div>
<div class="card"><h2>每日花费 <small>近 {DAYS} 天 · 悬停看明细</small></h2>{chart}</div>
<div class="card"><h2>用户 <small>按最近活跃排序 · 余额低于 ${low_usd:g} 标红</small></h2>{users_html}</div>
<div class="grid2">
<div class="card"><h2>被拦的登录 <small>邀请会给对方发邮件</small></h2>{wl_html}</div>
<div class="card"><h2>邀请 <small>已邀请、还没登录的人</small></h2>{invite_form}{pend_html}</div>
</div><div style="height:18px"></div>
<div class="card"><h2>按模型 <small>近 {DAYS} 天</small></h2>{model_html}</div>
<div class="card"><h2>最近反馈</h2>{fb_html}</div>
<div class="card"><h2>额度发放</h2>{gr_html}</div>
<p class="empty">这里只有账户汇总与用量元数据，不含任何用户空间里的内容。</p>
</div><script>{pages.THEME_TOGGLE_JS}</script>"""
    return pages._doc("后台 · joblander", body, extra_css=CSS)
