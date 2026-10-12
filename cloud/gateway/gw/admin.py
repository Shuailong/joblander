"""管理后台（/_gw/admin）：只给 ADMIN_EMAILS 看。用户、用量、名单、反馈一页看完，外加邀请 / 清掉 / 加额度。

只展示账户汇总与用量元数据（模型、token、花费、时间），看不到也不读任何用户空间里的内容。
"""

from __future__ import annotations

import html
import math
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
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;margin-bottom:18px}
.grid3 .card{margin-bottom:0;min-width:0}
.grid2 .card{margin-bottom:0;min-width:0}
.adm table{font-size:13px}
.adm th{text-align:left;font-weight:550;color:var(--ink-3);font-size:12px;padding:0 10px 8px 0;border-bottom:1px solid var(--line);white-space:nowrap}
.adm td{padding:8px 10px 8px 0;vertical-align:middle}
.adm td.n,.adm th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.adm td.dim{color:var(--ink-3);white-space:nowrap}
.adm span.dim{color:var(--ink-3);font-size:12px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2);white-space:nowrap}
.pill.ok{background:var(--accent-soft);border-color:transparent;color:var(--accent-ink)}
.pill.bad{color:var(--red)}
.low{color:var(--red);font-weight:600}
.adm form.inl{display:inline-flex;gap:6px;align-items:center;margin:0}
.adm input{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);color:var(--ink)}
.adm input.usd{width:62px}
.adm .tbtn{height:28px}
.adm .tbtn.go{background:var(--accent);color:var(--on-accent);border-color:transparent}
.plot{display:grid;grid-template-columns:auto 1fr auto;column-gap:6px;margin-top:8px}
.pa{position:relative;height:140px;min-width:0}
.yax{position:relative;height:140px;font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums;white-space:nowrap}
.yax span{position:absolute;right:0;transform:translateY(50%);line-height:1}
.yax.r span{right:auto;left:0}
.yax .w{display:block;visibility:hidden;height:0;font-weight:inherit}
.gl{position:absolute;left:0;right:0;border-top:1px dashed var(--line);pointer-events:none}
.gl.z{border-top-style:solid;border-color:var(--line-strong)}
.plot .axis{grid-column:2}
.chart{position:relative;display:flex;align-items:flex-end;gap:3px;height:100%}
.chart>div{flex:1;display:flex;flex-direction:column-reverse;height:100%;justify-content:flex-start}
.chart>div{cursor:default;border-radius:3px 3px 0 0}
.chart>div:hover,.chart>div.on{background:var(--accent-soft)}
.tip{position:fixed;z-index:50;pointer-events:none;background:var(--surface);border:1px solid var(--line-strong);
  border-radius:10px;padding:8px 11px;font-size:12.5px;line-height:1.6;box-shadow:var(--shadow-lg);
  white-space:nowrap;font-variant-numeric:tabular-nums}
.tip b{display:block;font-weight:620;margin-bottom:2px}
.tip i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;background:var(--accent)}
.tip i.a{opacity:.85}.tip i.b{opacity:.4}.tip i.c{background:#D99A2B;opacity:.7}
.tip i.l{height:2px;width:12px;vertical-align:3px;background:var(--ink-2)}
.chart i{display:block;min-height:0}
.chart i.a{background:var(--accent);opacity:.85}
.chart i.b{background:var(--accent);opacity:.4}
.chart i.c{background:#D99A2B;opacity:.7}
.chart i.z{background:var(--line);min-height:1px}
.chart>div>i:last-child{border-radius:3px 3px 0 0}
.plot svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
.plot path{fill:none;stroke:var(--ink-2);stroke-width:1.8;stroke-linejoin:round;stroke-linecap:round;vector-effect:non-scaling-stroke}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--ink-3);font-size:12px;margin:-4px 0 10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;background:var(--accent)}
.legend i.a{opacity:.85}.legend i.b{opacity:.4}.legend i.c{background:#D99A2B;opacity:.7}
.legend i.l{height:2px;width:14px;background:var(--ink-2);vertical-align:3px}
.axis{display:flex;justify-content:space-between;color:var(--ink-3);font-size:11.5px;margin-top:6px}
.axis span{white-space:nowrap}
.axis span:nth-child(2){overflow:hidden;text-overflow:ellipsis;min-width:0;padding:0 8px}
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


def mask(email: str) -> str:
    """后台里显示的邮箱打码：用户名只留头两位和末位（liangshuailong@gmail.com → li•••g@gmail.com）。"""
    name, at, dom = str(email or "").partition("@")
    if len(name) <= 3:
        name = name[:1] + "•••"
    else:
        name = name[:2] + "•••" + name[-1]
    return name + at + dom


def _tok(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"


ZERO = '<i class="z"></i>'
_WEEK = "一二三四五六日"


def _day(d: str) -> str:
    return f"{d[5:]} 周{_WEEK[datetime.strptime(d, '%Y-%m-%d').weekday()]}"


# 图表浮层：悬停（或手机上点按）某天的柱子，显示那天每一项的具体数字
TIP_JS = """(()=>{const t=document.createElement('div');t.className='tip';t.hidden=true;document.body.append(t);
let cur=null;const hov=matchMedia('(hover:hover)').matches;
function show(c){cur=c;t.replaceChildren();const [h,...ls]=c.dataset.tip.split('\\n');
const b=document.createElement('b');b.textContent=h;t.append(b);
for(const l of ls){const i=l.indexOf('|'),d=document.createElement('div');
if(i>0){const s=document.createElement('i');s.className=l.slice(0,i);d.append(s);}
d.append(l.slice(i+1));t.append(d);}
t.hidden=false;const r=c.getBoundingClientRect(),w=t.offsetWidth,h2=t.offsetHeight;
let x=r.left+r.width/2-w/2;x=Math.max(8,Math.min(x,innerWidth-w-8));
let y=r.top-h2-8;if(y<8)y=r.bottom+8;
t.style.left=x+'px';t.style.top=y+'px';c.classList.add('on');}
function hide(){t.hidden=true;if(cur)cur.classList.remove('on');cur=null;}
document.querySelectorAll('.chart>div[data-tip]').forEach(c=>{
if(hov){c.addEventListener('mouseenter',()=>{hide();show(c)});c.addEventListener('mouseleave',hide);}
c.addEventListener('click',e=>{e.stopPropagation();if(hov){hide();show(c)}else cur===c?hide():(hide(),show(c))});});
document.addEventListener('click',hide);addEventListener('scroll',hide,{passive:true});})();"""


def _nice(peak: float, n: int = 4, whole: bool = False) -> tuple[float, float]:
    """纵轴取整：顶到不小于 peak 的「1 / 2 / 2.5 / 5 × 10^k」档，返回 (顶, 步长)，约 n 格。"""
    if peak <= 0:
        return (4.0, 1.0) if whole else (1.0, .25)
    raw = peak / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    if whole:                                              # 人数：刻度只用整数
        step = max(1, math.ceil(step)) if step < 10 else step
    return step * math.ceil(peak / step - 1e-9), step


def _smooth(pts: list[tuple[float, float]]) -> str:
    """单调三次插值（Fritsch–Carlson）的 SVG 路径：曲线平滑，但不会冲过相邻点（花费不会画成负数）。"""
    n = len(pts)
    if n < 3:
        return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    d = [(pts[k + 1][1] - pts[k][1]) / (pts[k + 1][0] - pts[k][0]) for k in range(n - 1)]
    m = [d[0]] + [0.0 if d[k - 1] * d[k] <= 0 else (d[k - 1] + d[k]) / 2 for k in range(1, n - 1)] + [d[-1]]
    for k in range(n - 1):
        if d[k] == 0:
            m[k] = m[k + 1] = 0.0
            continue
        a, b = m[k] / d[k], m[k + 1] / d[k]
        if a * a + b * b > 9:
            t = 3 / math.hypot(a, b)
            m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    out = [f"M{pts[0][0]:.2f},{pts[0][1]:.2f}"]
    for k in range(n - 1):
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        h = (x1 - x0) / 3
        out.append(f"C{x0 + h:.2f},{y0 + m[k] * h:.2f} {x1 - h:.2f},{y1 - m[k + 1] * h:.2f} {x1:.2f},{y1:.2f}")
    return " ".join(out)


def _ticks(top: float, step: float, fmt) -> str:
    labels = [fmt(k * step) for k in range(round(top / step) + 1)]
    # 刻度绝对定位、不占宽；放一份看不见的最长标签把这一列撑开
    return (f'<b class="w">{max(labels, key=len)}</b>' +
            "".join(f'<span style="bottom:{k * step / top * 100:.2f}%">{t}</span>' for k, t in enumerate(labels)))


def _plot(days: list[str], stacks: list[tuple[float, ...]], tips: list[list[str]],
          line: list[float] | None = None, *, fmt=lambda v: f"{v:g}", line_fmt=lambda v: f"{v:g}",
          foot: str = "", whole: bool = False) -> str:
    """按天的柱图：每天几段自下而上堆叠（a 深、b 浅、c 琥珀），左侧纵轴刻度 + 横向网格线；
    可选一条平滑曲线，用右侧自己的纵轴。

    tips：每天一组行，第一行是标题；其余行写成「色块|文字」（色块 a/b/c/l 对应图例，空 = 不带色块），
    悬停 / 点按时由 TIP_JS 画成浮层。"""
    top, step = _nice(max((sum(st) for st in stacks), default=0), whole=whole)
    cols = []
    for st, tip in zip(stacks, tips):
        segs = "".join(f'<i class="{c}" style="height:{v / top * 100:.2f}%"></i>' for c, v in zip("abc", st) if v)
        cols.append(f'<div data-tip="{_e(chr(10).join(tip))}">{segs or ZERO}</div>')
    grid = "".join(f'<div class="gl{" z" if k == 0 else ""}" style="bottom:{k * step / top * 100:.2f}%"></div>'
                   for k in range(round(top / step) + 1))
    svg, right = "", ""
    if line:
        ltop, lstep = _nice(max(line))
        n = len(line)
        path = _smooth([((i + .5) / n * 100, 100 - v / ltop * 100) for i, v in enumerate(line)])
        svg = f'<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="{path}"/></svg>'
        right = _ticks(ltop, lstep, line_fmt)
    return (f'<div class="plot"><div class="yax">{_ticks(top, step, fmt)}</div>'
            f'<div class="pa">{grid}<div class="chart">{"".join(cols)}</div>{svg}</div>'
            f'<div class="yax r">{right}</div>{foot}</div>')


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def render(snap: dict, *, low_usd: float, tz_name: str, privacy_version: str, flash: str = "",
           now: float | None = None) -> HTMLResponse:
    now = now or time.time()
    tz = ZoneInfo(tz_name)
    users, usage = snap["users"], snap["usage"]
    day = 86400

    # ---- 汇总 ----
    week = {datetime.fromtimestamp(now - i * day, tz).strftime("%Y-%m-%d") for i in range(7)}
    active7 = ({u["email"] for u in usage if u["at"] >= now - 7 * day}
               | {a["email"] for a in snap.get("active_days", []) if a["day"] in week})
    cost = lambda since: sum(u["cost_usd"] for u in usage if u["at"] >= since)          # noqa: E731
    today0 = datetime.fromtimestamp(now, tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    total_spent = sum(u["spent_usd"] for u in users)
    lows = [u for u in users if u["credit_usd"] - u["spent_usd"] < low_usd]
    errs = snap.get("ai_errors", [])
    errs24 = [e for e in errs if e["at"] >= now - day]
    reqs = snap.get("credit_requests", [])
    pending_reqs = [r for r in reqs if r["status"] == "pending"]
    kpis = [
        (len(users), "用户", ""),
        (len(active7), "7 天活跃", ""),
        (f"${cost(today0):.2f}", "今天花费", ""),
        (f"${cost(now - 7 * day):.2f}", "7 天花费", ""),
        (f"${total_spent:.2f}", "累计花费", ""),
        (len(errs24), "24 小时 AI 失败", "warn" if errs24 else ""),
        (len(pending_reqs), "额度申请待批", "warn" if pending_reqs else ""),
        (len(snap["waitlist"]), "被拦待处理", "warn" if snap["waitlist"] else ""),
        (len(lows), f"余额 < ${low_usd:g}", "warn" if lows else ""),
    ]
    kpi_html = "".join(f'<div class="kpi {c}"><b>{v}</b><span>{label}</span></div>' for v, label, c in kpis)

    days = [datetime.fromtimestamp(now - i * day, tz).strftime("%Y-%m-%d") for i in range(DAYS - 1, -1, -1)]
    axis = lambda mid: (f'<div class="axis"><span>{days[0][5:]}</span><span>{mid}</span>'   # noqa: E731
                        f'<span>{days[-1][5:]}</span></div>')

    # ---- 用户增长：每天结束时的累计人数，按所处阶段堆叠（注册 / 已邀请未登录 / 被拦待处理）----
    # 每人取三个时间点：首次被拦、获邀、注册；当天处于最靠后的那一阶段。被清掉的被拦记录不计。
    stages: dict[str, list] = defaultdict(lambda: [None, None, None])
    for w in snap["waitlist"]:
        stages[w["email"]][0] = w["first_at"]
    for i in snap.get("invites", []):
        stages[i["email"]][1] = i["created_at"]
        if i.get("requested_at"):
            stages[i["email"]][0] = i["requested_at"]
    for u in users:
        stages[u["email"]][2] = u["created_at"]
    marks = {e: [_t(t, tz, "%Y-%m-%d") if t else None for t in ts] for e, ts in stages.items()}

    def stage_on(m: list, d: str) -> int:              # 2 注册 / 1 已邀请 / 0 被拦 / -1 还没出现
        return next((k for k in (2, 1, 0) if m[k] and m[k] <= d), -1)

    funnel, new_in = [], []
    for d in days:
        st = [stage_on(m, d) for m in marks.values()]
        funnel.append((st.count(2), st.count(1), st.count(0)))
        new_in.append(sum(1 for m in marks.values() if min(x for x in m if x) == d))
    grow = _plot(days, funnel, [[_day(d), f"a|已注册 {f[0]}", f"b|已邀请未登录 {f[1]}", f"c|被拦待处理 {f[2]}",
                                 f"|累计 {sum(f)} · 当天新来 {n}"] for d, f, n in zip(days, funnel, new_in)],
                 whole=True, foot=axis(f"{DAYS} 天新来 {sum(new_in)} · 累计 {sum(funnel[-1])}（注册 {funnel[-1][0]}）"))
    grow_html = ('<div class="legend"><span><i class="a"></i>已注册</span><span><i class="b"></i>已邀请未登录</span>'
                 '<span><i class="c"></i>被拦待处理</span></div>'
                 + grow)

    # ---- 每日活跃（新 = 当天注册；老 = 之前注册、当天用过）----
    joined = {u["email"]: _t(u["created_at"], tz, "%Y-%m-%d") for u in users}
    active: dict[str, set] = defaultdict(set)
    for a in snap.get("active_days", []):
        active[a["day"]].add(a["email"])
    for u in usage:                                          # 记活跃日之前的日子：调过 AI 也算用过
        active[_t(u["at"], tz, "%Y-%m-%d")].add(u["email"])
    new = [sum(1 for j in joined.values() if j == d) for d in days]
    old = [len({e for e in active[d] if e in joined and joined[e] < d}) for d in days]
    act = _plot(days, list(zip(new, old)), [[_day(d), f"a|新用户 {n}", f"b|老用户 {o}", f"|合计活跃 {n + o}"]
                                            for d, n, o in zip(days, new, old)],
                whole=True, foot=axis(f"今天活跃 {new[-1] + old[-1]} · {DAYS} 天新注册 {sum(new)}"))
    act_html = ('<div class="legend"><span><i class="a"></i>新用户（当天注册）</span>'
                '<span><i class="b"></i>老用户（当天用过）</span></div>'
                + act)

    # ---- 每日 token 与花费 ----
    fail_day: dict[str, int] = defaultdict(int)
    for e in errs:
        fail_day[_t(e["at"], tz, "%Y-%m-%d")] += 1
    per_day: dict[str, list] = defaultdict(lambda: [0, 0, 0.0, 0])
    for u in usage:
        k = per_day[_t(u["at"], tz, "%Y-%m-%d")]
        k[0] += u["prompt_tokens"]; k[1] += u["completion_tokens"]; k[2] += u["cost_usd"]; k[3] += 1
    tok = _plot(days, [(per_day[d][1], per_day[d][0]) for d in days],
                [[_day(d), f"a|输出 {per_day[d][1]:,} token", f"b|输入 {per_day[d][0]:,} token",
                  f"l|花费 ${per_day[d][2]:.3f}", f"|{per_day[d][3]} 次调用"
                  + (f" · 失败 {fail_day[d]} 次" if fail_day[d] else "")] for d in days],
                [per_day[d][2] for d in days], fmt=_tok, line_fmt=lambda v: f"${v:g}",
                foot=axis(f"{DAYS} 天 {_tok(sum(per_day[d][0] + per_day[d][1] for d in days))} token · "
                          f"${sum(per_day[d][2] for d in days):.2f}"))
    tok_html = ('<div class="legend"><span><i class="a"></i>输出 token</span><span><i class="b"></i>输入 token</span>'
                '<span><i class="l"></i>花费（右轴）</span></div>' + tok)

    # ---- AI 失败（按天 × 状态码 × 类型汇总）----
    eg: dict[tuple, list] = {}
    for e in errs:
        k = (_t(e["at"], tz, "%Y-%m-%d"), e["status"], e["kind"])
        g = eg.setdefault(k, [0, set(), 0.0])
        g[0] += 1; g[1].add(e["email"]); g[2] = e["at"]
    err_html = ('<table><tr><th>日期</th><th>状态</th><th>类型</th><th class="n">次数</th><th class="n">涉及用户</th>'
                '<th>最近一次</th></tr>' + "".join(
                    f'<tr><td class="dim">{k[0][5:]}</td><td>{k[1]}</td><td>{_e(k[2])}</td><td class="n">{v[0]}</td>'
                    f'<td class="n">{len(v[1])}</td><td class="dim">{_t(v[2], tz, "%H:%M")}</td></tr>'
                    for k, v in sorted(eg.items(), key=lambda kv: -kv[1][2])[:15]) + '</table>'
                if eg else f'<p class="empty">{DAYS} 天内没有失败</p>')

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
        return (f'<tr><td>{_e(mask(u["email"]))}{err}</td>'
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
        return (f'<tr><td>{_e(mask(w["email"]))}</td><td class="n">{w["attempts"]} 次</td><td class="dim">{_t(w["last_at"], tz)}</td>'
                f'<td class="dim">{_e(w["lang"] or "—")}</td><td style="white-space:nowrap">'
                f'<form class="inl" method="post" action="/_gw/admin/invite"><input type="hidden" name="email" value="{e}">'
                f'<button class="tbtn go">邀请</button></form> '
                f'<form class="inl" method="post" action="/_gw/admin/dismiss"><input type="hidden" name="email" value="{e}">'
                f'<button class="tbtn">清掉</button></form></td></tr>')

    wl_html = ('<table>' + "".join(wl_row(w) for w in snap["waitlist"]) + '</table>'
               if snap["waitlist"] else '<p class="empty">没有被拦的人</p>')
    pend_html = ('<table>' + "".join(f'<tr><td>{_e(mask(i["email"]))}</td><td class="dim">邀请于 {_t(i["created_at"], tz)}</td></tr>'
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

    # ---- 额度申请 ----
    def req_row(r: dict) -> str:
        bal = (r["credit_usd"] or 0) - (r["spent_usd"] or 0)
        who = (f'<td>{_e(mask(r["email"]))}<br><span class="dim">{_t(r["at"], tz)} · 余额 {_usd(bal)} · '
               f'已花 ${r["spent_usd"] or 0:.2f}</span></td><td class="fb">{_e(r["message"][:1200])}</td>')
        if r["status"] != "pending":
            done = (f'<span class="pill ok">已批 ${r["amount_usd"]:g}</span>' if r["status"] == "approved"
                    else '<span class="pill">未批准</span>')
            return f'<tr>{who}<td style="white-space:nowrap">{done} <span class="dim">{_t(r["decided_at"], tz)}</span></td></tr>'
        return (f'<tr>{who}<td style="white-space:nowrap"><form class="inl" method="post" action="/_gw/admin/request">'
                f'<input type="hidden" name="id" value="{r["id"]}">'
                f'<input class="usd" name="usd" type="number" step="0.5" min="0.5" max="100" value="5" aria-label="美元">'
                f'<button class="tbtn go" name="action" value="approve">批准</button>'
                f'<button class="tbtn" name="action" value="decline">不批</button></form></td></tr>')

    req_html = ('<table>' + "".join(req_row(r) for r in reqs) + '</table>' if reqs
                else '<p class="empty">没有额度申请</p>')

    # ---- 反馈 / 发放 ----
    fb_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(f["at"], tz)}</td><td>{_e(mask(f["email"]))}<br><span class="dim">{_e(f["page"])}</span></td>'
        f'<td class="fb">{_e(f["message"][:600])}</td><td class="dim">{"✉" if f["emailed"] else "·"}</td></tr>'
        for f in snap["feedback"]) + '</table>' if snap["feedback"] else '<p class="empty">还没有反馈</p>')
    gr_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(g["at"], tz)}</td><td>{_e(mask(g["email"]))}</td>'
        f'<td class="n">${g["amount_usd"]:.2f}</td><td class="dim">{_e(g["reason"])}</td></tr>'
        for g in snap["grants"]) + '</table>' if snap["grants"] else '<p class="empty">没有发放记录</p>')

    body = f"""<div class="adm">
<header><a href="/"><img src="{pages.LOGO}" alt=""></a><h1>后台</h1><span class="sp"></span>
<span class="when">{_t(now, tz, "%Y-%m-%d %H:%M")} {_e(tz_name)}</span>
<button class="tbtn" onclick="jlTheme()" title="切换深浅色">{pages.icon("moon", 15)}</button>
<a class="tbtn" href="/">返回</a></header>
{f'<div class="flash">{_e(flash)}</div>' if flash else ''}
<div class="kpis">{kpi_html}</div>
<div class="card" id="requests"><h2>额度申请 <small>用户在应用里写的用途与反馈 · 批准即发额度并邮件通知</small></h2>{req_html}</div>
<div class="grid3">
<div class="card"><h2>用户增长 <small>累计 · 含被拦与已邀请 · 悬停或点按看明细</small></h2>{grow_html}</div>
<div class="card"><h2>每日活跃 <small>近 {DAYS} 天 · 悬停或点按看明细</small></h2>{act_html}</div>
<div class="card"><h2>每日 token 与花费 <small>近 {DAYS} 天 · 悬停或点按看明细</small></h2>{tok_html}</div>
</div>
<div class="card"><h2>用户 <small>按最近活跃排序 · 余额低于 ${low_usd:g} 标红</small></h2>{users_html}</div>
<div class="grid2">
<div class="card"><h2>被拦的登录 <small>邀请会给对方发邮件</small></h2>{wl_html}</div>
<div class="card"><h2>邀请 <small>已邀请、还没登录的人</small></h2>{invite_form}{pend_html}</div>
</div><div style="height:18px"></div>
<div class="card"><h2>按模型 <small>近 {DAYS} 天</small></h2>{model_html}</div>
<div class="card"><h2>AI 调用失败 <small>上游限流 / 额度 / 网络 · 首次出现会邮件告警</small></h2>{err_html}</div>
<div class="card"><h2>最近反馈</h2>{fb_html}</div>
<div class="card"><h2>额度发放</h2>{gr_html}</div>
<p class="empty">这里只有账户汇总与用量元数据，不含任何用户空间里的内容。</p>
</div><script>{pages.THEME_TOGGLE_JS}{TIP_JS}</script>"""
    return pages._doc("后台 · joblander", body, extra_css=CSS)
