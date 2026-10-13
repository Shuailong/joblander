"""管理后台（/_gw/admin）：只给 ADMIN_EMAILS 看。用户、用量、名单、反馈一页看完，外加邀请 / 清掉 / 加额度。

只展示账户汇总与用量元数据（模型、token、花费、时间），看不到也不读任何用户空间里的内容。
"""

from __future__ import annotations

import html
import math
import time
import json
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

from gw import pages
from gw.geo import mask_ip

DAYS = 30
PAGE = 10                                           # 每张表一页几条：超过就分页
# 后台的查询参数：q 搜邮箱；其余是各表的页码（用户 / 被拦 / 额度申请 / 待登录邀请 / 反馈 / 发放 /
# AI 失败 / 功能使用 / 回访 / 按模型 / 国家 / 城市）
RET_KEYS = ("q", "pu", "pw", "pr", "pi", "pf", "pg", "pe", "pt", "pv", "pm", "pc", "py", "pb", "ps")

_STATUS = {"ready": "就绪", "asleep": "休眠", "new": "未开通", "provisioning": "开通中", "failed": "开通失败", "deleting": "删除中"}

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
.fn{display:grid;grid-template-columns:minmax(150px,240px) 1fr 54px 64px 64px;gap:6px 12px;align-items:center;font-size:13px}
.fn .hd{color:var(--ink-3);font-size:12px}
.fn .bar{height:18px;background:var(--surface-2);border-radius:5px;overflow:hidden}
.fn .bar i{display:block;height:100%;background:var(--accent);opacity:.8;border-radius:5px}
.fn .n{text-align:right;font-variant-numeric:tabular-nums}
.fn .drop{color:var(--red)}
.ret td.c{text-align:right;font-variant-numeric:tabular-nums}
.pager{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:12px;font-size:12.5px;color:var(--ink-3)}
.pager a,.pager b{min-width:28px;height:26px;padding:0 7px;display:inline-flex;align-items:center;justify-content:center;
  border-radius:7px;border:1px solid var(--line);color:var(--ink-2);text-decoration:none;font-variant-numeric:tabular-nums}
.pager b{background:var(--accent-soft);color:var(--accent-ink);border-color:transparent;font-weight:600}
.pager a:hover{border-color:var(--line-strong)}
.pager .tot{margin-left:auto}
.bulkbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:-2px 0 10px;font-size:13px}
.bulkbar .seln{color:var(--accent-ink);font-weight:600;min-width:52px}
.bulkbar .allbtn[hidden]{display:none}
.bulkbar .tbtn:disabled{opacity:.45;cursor:not-allowed}
.adm td.ck,.adm th.ck{width:22px;padding-right:6px}
.adm input[type=checkbox]{width:15px;height:15px;accent-color:var(--accent);vertical-align:-2px;cursor:pointer}
.srch{display:flex;gap:6px;align-items:center}
.srch input{width:210px}
.loc{white-space:nowrap}
.loc small{display:block;color:var(--ink-3);font-size:11.5px}
.pill.warn{color:#B07414;border-color:color-mix(in srgb,#D99A2B 45%,transparent)}
.map{position:relative;width:100%;aspect-ratio:2/1;max-height:460px;background:var(--surface-2);border-radius:10px;overflow:hidden}
.map svg{width:100%;height:100%;display:block;cursor:grab}
.map svg:active{cursor:grabbing}
.map .land{fill:var(--surface);stroke:var(--line-strong);stroke-width:.5;vector-effect:non-scaling-stroke}
.map circle{vector-effect:non-scaling-stroke;stroke:var(--surface);stroke-width:1.5}
.map circle.all{fill:#D99A2B;fill-opacity:.75}
.map circle.reg{fill:var(--accent);fill-opacity:.9;pointer-events:none}
.map circle.all:hover{fill-opacity:1}
.map .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--ink-3);font-size:13px}
.map .zb{position:absolute;right:10px;top:10px;display:flex;flex-direction:column;gap:4px}
.map .zb button{width:28px;height:28px;padding:0;justify-content:center}
.geo2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:14px}
.share{display:inline-block;width:70px;height:7px;border-radius:4px;background:var(--surface-2);vertical-align:1px;margin-left:6px;overflow:hidden}
.share i{display:block;height:100%;background:var(--accent);opacity:.75}
.foot{color:var(--ink-3);font-size:12px}
.foot a{color:inherit}
@media (max-width:820px){.geo2{grid-template-columns:1fr}.srch input{width:150px}}
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


def _slice(rows: list, key: str, params: dict) -> tuple[list, int, int]:
    """取第几页（参数 key，从 1 起；越界就夹到首尾），返回 (这页的行, 页码, 总页数)。"""
    try:
        p = int(params.get(key) or 1)
    except ValueError:
        p = 1
    n = max(1, math.ceil(len(rows) / PAGE))
    p = min(max(p, 1), n)
    return rows[(p - 1) * PAGE:p * PAGE], p, n


def _pager(key: str, p: int, n: int, total: int, params: dict, anchor: str) -> str:
    """翻页条：首页、当前页前后两页、末页，中间用省略号；只有一页时只显示总数。"""
    if total <= PAGE:
        return ""

    def link(k: int, label: str = "") -> str:
        q = urlencode({**params, key: k}) if k > 1 else urlencode({x: v for x, v in params.items() if x != key})
        return f'<a href="?{_e(q)}#{anchor}">{label or k}</a>'
    shown = sorted({1, n, *range(max(1, p - 2), min(n, p + 2) + 1)})
    out, last = [link(p - 1, "‹") if p > 1 else ""], 0
    for k in shown:
        if k - last > 1:
            out.append("<span>…</span>")
        out.append(f"<b>{k}</b>" if k == p else link(k))
        last = k
    out.append(link(p + 1, "›") if p < n else "")
    a, b = (p - 1) * PAGE + 1, min(p * PAGE, total)
    return f'<div class="pager">{"".join(out)}<span class="tot">第 {a}–{b} 条 · 共 {total} 条</span></div>'


def _loc(g: dict | None) -> str:
    """表格里的「地区」格：城市 · 国家，下面一行打码的 IP。"""
    if not g:
        return '<td class="dim">—</td>'
    place = " · ".join(x for x in (g["city"], g["country_name"]) if x) or "未知"
    return (f'<td class="loc" title="{_e(g["region"] or "")}">{_e(place)}'
            f'<small>{_e(mask_ip(g["ip"]))}</small></td>')


# 勾选批量：全选本页、Shift 连选、显示已选几条；没勾选时批量按钮置灰
# 本页全选后，有别的页时出现「选中全部 N 个」：提交 all=1，服务端对当前搜索下的全部条目生效
BULK_JS = """document.querySelectorAll('form.bulk').forEach(f=>{
const all=f.querySelector('input.all'),bx=[...f.querySelectorAll('input[name=sel]')],n=f.querySelector('.seln');let last=null;
const ab=f.querySelector('.allbtn'),ai=f.querySelector('input[name=all]'),tot=+f.dataset.total||0;
const upd=()=>{const k=bx.filter(b=>b.checked).length,whole=ai&&ai.value==='1';
if(whole&&k<bx.length)ai.value='';const w=ai&&ai.value==='1';
if(n)n.textContent=w?'已选全部 '+tot:k?'已选 '+k:'';
f.querySelectorAll('.bulkbtn').forEach(b=>b.disabled=!k);
if(ab)ab.hidden=!(k===bx.length&&k>0&&tot>bx.length&&!w);
if(all){all.checked=k>0&&k===bx.length;all.indeterminate=k>0&&k<bx.length;}};
if(ab)ab.addEventListener('click',()=>{ai.value='1';upd();});
if(all)all.addEventListener('change',()=>{bx.forEach(b=>b.checked=all.checked);upd();});
bx.forEach((b,i)=>b.addEventListener('click',e=>{if(e.shiftKey&&last!==null){const [a,z]=[Math.min(last,i),Math.max(last,i)];
for(let j=a;j<=z;j++)bx[j].checked=b.checked;}last=i;upd();}));upd();});"""

# 世界地图：d3-geo + world-atlas（jsDelivr）；每个城市一个圈——外圈琥珀 = 总人数，内圈深色 = 其中已注册，面积正比人数。
# 滚轮 / 按钮缩放、拖动平移；悬停或点按看明细。脚本加载失败时只显示提示，下面的表照样能看。
MAP_JS = """(()=>{const box=document.getElementById('geomap');if(!box)return;const pts=JSON.parse(document.getElementById('geodata').textContent);
const msg=t=>{box.querySelector('.msg').textContent=t};
if(!window.d3||!window.topojson){msg('地图脚本没加载出来——看下面的表');return;}
if(!pts.length){msg('还没有带地点的记录：用户下次登录或访问后出现');return;}
fetch('https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json').then(r=>r.json()).then(w=>{
box.querySelector('.msg').remove();const W=960,H=480;
const svg=d3.select(box).insert('svg',':first-child').attr('viewBox',`0 0 ${W} ${H}`).attr('role','img')
  .attr('aria-label','用户所在城市分布图');
const proj=d3.geoNaturalEarth1().fitExtent([[8,8],[W-8,H-8]],{type:'Sphere'}),path=d3.geoPath(proj);
const g=svg.append('g');
g.append('path').attr('class','land').attr('d',path(topojson.feature(w,w.objects.countries)));
const max=d3.max(pts,p=>p.n),r=d3.scaleSqrt().domain([0,max]).range([0,Math.min(26,6+Math.sqrt(max)*3)]);
const tip=document.querySelector('.tip')||Object.assign(document.body.appendChild(document.createElement('div')),{className:'tip',hidden:true});
let k=1;const R=v=>Math.max(2.5,r(v))/Math.sqrt(k);
const ds=pts.slice().sort((a,b)=>b.n-a.n);
const all=g.selectAll('circle.all').data(ds).join('circle').attr('class','all');
const reg=g.selectAll('circle.reg').data(ds.filter(p=>p.reg)).join('circle').attr('class','reg');
const place=()=>{all.attr('cx',p=>proj([p.lon,p.lat])[0]).attr('cy',p=>proj([p.lon,p.lat])[1]).attr('r',p=>R(p.n));
reg.attr('cx',p=>proj([p.lon,p.lat])[0]).attr('cy',p=>proj([p.lon,p.lat])[1]).attr('r',p=>R(p.n)*Math.sqrt(p.reg/p.n));};
place();
const show=(e,p)=>{tip.replaceChildren();const b=document.createElement('b');b.textContent=p.label;tip.append(b);
for(const [c,t] of [['',`共 ${p.n} 人`],['',`已注册 ${p.reg}`],['c',`被拦待处理 ${p.wl}`],['b',`已邀请未登录 ${p.inv}`]]){
 const d=document.createElement('div');if(c){const s=document.createElement('i');s.className=c;d.append(s);}d.append(t);tip.append(d);}
tip.hidden=false;const w2=tip.offsetWidth,h2=tip.offsetHeight;let x=e.clientX-w2/2,y=e.clientY-h2-14;
x=Math.max(8,Math.min(x,innerWidth-w2-8));if(y<8)y=e.clientY+14;tip.style.left=x+'px';tip.style.top=y+'px';};
all.on('mousemove',show).on('click',(e,p)=>{e.stopPropagation();show(e,p);}).on('mouseleave',()=>{tip.hidden=true;});
const z=d3.zoom().scaleExtent([1,12]).translateExtent([[0,0],[W,H]]).on('zoom',e=>{k=e.transform.k;g.attr('transform',e.transform);place();});
svg.call(z);box.querySelector('.zin').onclick=()=>svg.transition().call(z.scaleBy,2);
box.querySelector('.zout').onclick=()=>svg.transition().call(z.scaleBy,.5);
box.querySelector('.zre').onclick=()=>svg.transition().call(z.transform,d3.zoomIdentity);
}).catch(()=>msg('世界地图数据没加载出来——看下面的表'));})();"""


def render(snap: dict, *, low_usd: float, tz_name: str, privacy_version: str, flash: str = "",
           asleep: set[str] | None = None, params: dict | None = None, mail: dict | None = None,
           now: float | None = None, budget: tuple[float, float] | None = None) -> HTMLResponse:
    now = now or time.time()
    tz = ZoneInfo(tz_name)
    users, usage = snap["users"], snap["usage"]
    day = 86400
    params = {k: str(v) for k, v in (params or {}).items() if k in RET_KEYS and v}
    q = params.get("q", "").strip().lower()
    hit = (lambda e: q in e) if q else (lambda e: True)                                 # noqa: E731
    # 每个表单都带上当前的分页 / 搜索，操作完回到原处
    ret = f'<input type="hidden" name="ret" value="{_e(urlencode(params))}">'
    geo = {g["email"]: g for g in snap.get("geo", [])}

    def paged(rows: list, key: str, anchor: str) -> tuple[list, str]:
        """取这张表当前页的行，连同它的翻页条。"""
        page, p, n = _slice(rows, key, params)
        return page, _pager(key, p, n, len(rows), params, anchor)

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
        *([(f"${budget[0]:.2f} / ${budget[1]:g}", f"本月花费 / 预算（{budget[0] / budget[1] * 100:.0f}%）",
            "warn" if budget[0] >= .7 * budget[1] else "") if budget[1] > 0 else
           (f"${budget[0]:.2f}", "本月花费（未设预算上限）", "warn")] if budget else []),
        (len(errs24), "24 小时 AI 失败", "warn" if errs24 else ""),
        *([(f'{sum(1 for u in users if u["status"] == "ready" and u["email"] not in asleep)}'
            f' / {sum(1 for u in users if u["status"] == "ready")}', "机器在线（其余休眠）", "")]
          if asleep is not None else []),
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
    err_rows, err_pg = paged(sorted(eg.items(), key=lambda kv: -kv[1][2]), "pe", "errors")
    err_html = ('<table><tr><th>日期</th><th>状态</th><th>类型</th><th class="n">次数</th><th class="n">涉及用户</th>'
                '<th>最近一次</th></tr>' + "".join(
                    f'<tr><td class="dim">{k[0][5:]}</td><td>{k[1]}</td><td>{_e(k[2])}</td><td class="n">{v[0]}</td>'
                    f'<td class="n">{len(v[1])}</td><td class="dim">{_t(v[2], tz, "%H:%M")}</td></tr>'
                    for k, v in err_rows) + '</table>' + err_pg
                if eg else f'<p class="empty">{DAYS} 天内没有失败</p>')

    # ---- BI：漏斗 / 功能使用 / 回访 ----
    from gw import bi
    b = bi.compute(snap, tz, now, DAYS)
    top0 = b["funnel"][0][1] or 1
    rows = ['<span class="hd">步骤</span><span class="hd"></span><span class="hd n">人数</span>'
            '<span class="hd n">较上一步</span><span class="hd n">停在这步</span>']
    for i, ((title, n), stuck) in enumerate(zip(b["funnel"], b["stuck"])):
        prev = b["funnel"][i - 1][1] if i else n
        rate = f"{n / prev * 100:.0f}%" if i and prev else "—"
        low = i and prev and n / prev < .6
        rows.append(f'<span>{_e(title)}</span><span class="bar"><i style="width:{n / top0 * 100:.1f}%"></i></span>'
                    f'<span class="n">{n}</span><span class="n{" drop" if low else ""}">{rate}</span>'
                    f'<span class="n dim">{stuck if i < len(b["funnel"]) - 1 else "—"}</span>')
    since_note = (f'使用记录 {b["tracked_since"][5:]} 起才有；更早的人按「走到后一步、前面都算走过」补齐'
                  if b["tracked_since"] else "使用记录还没有数据：用户机器升级到新版后开始采集")
    funnel_html = f'<div class="fn">{"".join(rows)}</div>'
    feat_rows, feat_pg = paged(b["features"], "pt", "features")
    feat_html = ('<table><tr><th>功能</th><th class="n">用过的人</th><th class="n">次数</th></tr>' + "".join(
        f'<tr><td title="{_e(k)}">{_e(label)}</td><td class="n">{nu}</td><td class="n">{nc:,}</td></tr>'
        for label, k, nu, nc in feat_rows) + '</table>' + feat_pg
                 if b["features"] else '<p class="empty">还没有使用记录</p>')

    def cell(c):
        return '<td class="c dim">—</td>' if c is None else f'<td class="c">{c[0]}/{c[1]} · {c[0] / c[1] * 100:.0f}%</td>'
    ret_rows, ret_pg = paged(b["retention"], "pv", "retention")
    ret_html = ('<table class="ret"><tr><th>注册日</th><th class="n">人数</th><th class="n">次日回来</th>'
                '<th class="n">3 天内回来</th><th class="n">7 天内回来</th></tr>' + "".join(
                    f'<tr><td class="dim">{d[5:]}</td><td class="n">{n}</td>{"".join(cell(c) for c in cs)}</tr>'
                    for d, n, cs in ret_rows) + '</table>' + ret_pg
                if b["retention"] else '<p class="empty">还没有用户</p>')

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
        if st == "ready" and asleep is not None and u["email"] in asleep:
            st, pill = "asleep", ""
        consent = ("✓" if u["privacy_version"] == privacy_version
                   else ("旧版" if u["privacy_version"] else "未同意"))
        err = f'<br><span class="dim" title="{_e(u["error"])}">{_e(u["error"])[:60]}</span>' if u["error"] else ""
        return (f'<tr><td>{_e(mask(u["email"]))}{err}</td>'
                f'<td><span class="pill {pill}">{_STATUS.get(st, _e(st))}</span></td>'
                f'<td class="dim">{_e(u["lang"] or "—")}</td>{_loc(geo.get(u["email"]))}'
                f'<td class="dim">{_t(u["created_at"], tz)}</td>'
                f'<td class="dim" title="{_t(u["last_at"], tz)}">{_ago(u["last_at"], now)}</td>'
                f'<td class="n">{calls7[u["email"]]} / {u["calls"]}</td>'
                f'<td class="n">${cost7[u["email"]]:.2f} / ${u["spent_usd"]:.2f}</td>'
                f'<td class="n {"low" if bal < low_usd else ""}">{_usd(bal)}</td>'
                f'<td class="dim">{consent}</td>'
                f'<td><form class="inl" method="post" action="/_gw/admin/grant">{ret}'
                f'<input type="hidden" name="email" value="{_e(u["email"])}">'
                f'<input class="usd" name="usd" type="number" step="0.5" min="0.5" max="100" value="5" aria-label="美元">'
                f'<button class="tbtn">加额度</button></form></td></tr>')

    shown_users = [u for u in users if hit(u["email"])]
    page_users, p, n = _slice(shown_users, "pu", params)
    users_html = ('<table><tr><th>邮箱</th><th>机器</th><th>语言</th><th>地区</th><th>注册</th><th>最近活跃</th>'
                  '<th class="n">调用 7天/累计</th><th class="n">花费 7天/累计</th><th class="n">余额</th>'
                  '<th>隐私同意</th><th></th></tr>' + "".join(user_row(u) for u in page_users) + '</table>'
                  + _pager("pu", p, n, len(shown_users), params, "users")
                  if shown_users else f'<p class="empty">{"没有匹配的用户" if q else "还没有用户"}</p>')

    # ---- 名单：整张表是一个表单；勾选后表头按钮批量处理，行内按钮只处理那一行 ----
    def wl_row(w: dict) -> str:
        e = _e(w["email"])
        return (f'<tr><td class="ck"><input type="checkbox" name="sel" value="{e}" aria-label="选中"></td>'
                f'<td>{_e(mask(w["email"]))}</td><td class="n">{w["attempts"]} 次</td>'
                f'<td class="dim">{_t(w["last_at"], tz)}</td><td class="dim">{_e(w["lang"] or "—")}</td>'
                f'{_loc(geo.get(w["email"]))}<td style="white-space:nowrap">'
                f'<button class="tbtn go" name="act" value="invite:{e}">邀请</button> '
                f'<button class="tbtn" name="act" value="dismiss:{e}">清掉</button></td></tr>')

    shown_wl = [w for w in snap["waitlist"] if hit(w["email"])]
    page_wl, p, n = _slice(shown_wl, "pw", params)
    wl_html = (f'<form class="bulk" method="post" action="/_gw/admin/waitlist" data-total="{len(shown_wl)}">' + ret +
               '<input type="hidden" name="all" value="">'
               '<div class="bulkbar"><span class="seln"></span>'
               f'<button type="button" class="tbtn allbtn" hidden>选中全部 {len(shown_wl)} 人（含其他页）</button>'
               '<button class="tbtn go bulkbtn" name="act" value="invite">邀请选中的人</button>'
               '<button class="tbtn bulkbtn" name="act" value="dismiss">清掉选中的人</button></div>'
               '<table><tr><th class="ck"><input type="checkbox" class="all" aria-label="全选本页"></th>'
               '<th>邮箱</th><th class="n">尝试</th><th>最近</th><th>语言</th><th>地区</th><th></th></tr>'
               + "".join(wl_row(w) for w in page_wl) + '</table></form>'
               + _pager("pw", p, n, len(shown_wl), params, "waitlist")
               if shown_wl else f'<p class="empty">{"没有匹配的人" if q else "没有被拦的人"}</p>')
    shown_inv = [i for i in snap["pending_invites"] if hit(i["email"])]
    page_inv, p, n = _slice(shown_inv, "pi", params)
    queued_inv = set(snap.get("queued_invites", []))

    def inv_mail(i: dict) -> str:
        if i.get("mailed_at"):
            return ""
        return ('<span class="pill">邮件排队中</span>' if i["email"] in queued_inv
                else '<span class="pill warn">邮件未发出</span>')
    unmailed = sum(1 for i in snap["pending_invites"] if not i.get("mailed_at") and i["email"] not in queued_inv)
    pend_html = ('<table>' + "".join(
        f'<tr><td>{_e(mask(i["email"]))}</td><td class="dim">邀请于 {_t(i["created_at"], tz)}</td>'
        f'<td>{inv_mail(i)}</td></tr>'
        for i in page_inv) + '</table>' + _pager("pi", p, n, len(shown_inv), params, "invites")
                 if shown_inv else '<p class="empty">邀请过的人都已登录</p>')
    if snap["pending_invites"]:
        pend_html += (f'<form class="inl" method="post" action="/_gw/admin/remind-invites" style="margin:10px 8px 0 0">{ret}'
                      f'<button class="tbtn">给这 {len(snap["pending_invites"])} 人发登录提醒</button></form>')
    if unmailed:
        pend_html += (f'<form class="inl" method="post" action="/_gw/admin/resend-invites" style="margin-top:10px">{ret}'
                      f'<button class="tbtn">重发 {unmailed} 封没发出的邀请邮件</button></form>')
    invite_form = (f'<form class="inl" method="post" action="/_gw/admin/invite" style="margin-bottom:12px">{ret}'
                   '<input name="email" type="email" required placeholder="name@gmail.com" style="width:230px">'
                   '<button class="tbtn go">邀请</button></form>')

    # ---- 按模型 ----
    by_model: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0.0])
    for u in usage:
        m = by_model[u["model"]]
        m[0] += 1; m[1] += u["prompt_tokens"]; m[2] += u["completion_tokens"]; m[3] += u["cost_usd"]
    model_rows, model_pg = paged(sorted(by_model.items(), key=lambda kv: -kv[1][3]), "pm", "models")
    model_html = ('<table><tr><th>模型</th><th class="n">调用</th><th class="n">输入 token</th>'
                  '<th class="n">输出 token</th><th class="n">花费</th></tr>' + "".join(
                      f'<tr><td>{_e(k)}</td><td class="n">{v[0]}</td><td class="n">{v[1]:,}</td>'
                      f'<td class="n">{v[2]:,}</td><td class="n">${v[3]:.3f}</td></tr>'
                      for k, v in model_rows) + '</table>' + model_pg
                  if by_model else f'<p class="empty">{DAYS} 天内没有调用</p>')

    # ---- 按功能花费 + 每人花费分布 ----
    by_feat: dict[str, list] = defaultdict(lambda: [0, set(), 0.0, 0, 0])   # 调用 / 人 / 花费 / 耗时和 / 有耗时的次数
    per_user: dict[str, float] = defaultdict(float)
    for u in usage:
        f = by_feat[u.get("feature") or ""]
        f[0] += 1; f[1].add(u["email"]); f[2] += u["cost_usd"]
        if u.get("latency_ms") is not None:
            f[3] += u["latency_ms"]; f[4] += 1
        per_user[u["email"]] += u["cost_usd"]
    tagged = sum(v[2] for k, v in by_feat.items() if k)
    all_cost = sum(v[2] for v in by_feat.values()) or 1

    def feat_label(k: str) -> str:
        if not k:
            return "未标注（引擎升级前的调用）"
        if k.startswith("job:"):
            return f"定时：{bi.JOB_LABELS.get(k[4:], k[4:])}"
        return bi.LABELS.get(k, k)
    fc_rows, fc_pg = paged(sorted(by_feat.items(), key=lambda kv: -kv[1][2]), "pb", "featcost")
    costs = sorted(per_user.values())

    def pct(p: float) -> float:
        return costs[min(len(costs) - 1, int(p * len(costs)))] if costs else 0.0
    featcost_html = ('<table><tr><th>功能</th><th class="n">调用</th><th class="n">人</th><th class="n">花费</th>'
                     '<th class="n">占比</th><th class="n">每次</th><th class="n">平均耗时</th></tr>' + "".join(
                         f'<tr><td title="{_e(k)}">{_e(feat_label(k))}</td><td class="n">{v[0]}</td>'
                         f'<td class="n">{len(v[1])}</td><td class="n">${v[2]:.3f}</td>'
                         f'<td class="n">{v[2] / all_cost * 100:.0f}%</td><td class="n">${v[2] / v[0]:.4f}</td>'
                         f'<td class="n">{f"{v[3] / v[4] / 1000:.1f}s" if v[4] else "—"}</td></tr>'
                         for k, v in fc_rows) + '</table>' + fc_pg +
                     f'<p class="foot">每人 {DAYS} 天花费（{len(costs)} 个用过 AI 的人）：中位数 ${pct(.5):.3f} · '
                     f'P90 ${pct(.9):.3f} · P99 ${pct(.99):.3f} · 最高 ${costs[-1] if costs else 0:.3f}'
                     f' · 已标注功能的花费占 {tagged / all_cost * 100:.0f}%</p>'
                     if by_feat else f'<p class="empty">{DAYS} 天内没有调用</p>')

    # ---- 来源：第一次登录时从哪来 ----
    reg_set = {u["email"] for u in users}
    by_src: dict[str, list] = defaultdict(lambda: [0, 0])                  # 合计 / 已注册
    for s in snap.get("sources", []):
        key = " · ".join(x for x in (s.get("utm_source"), s.get("utm_campaign")) if x) or s.get("ref") or ""
        by_src[key][0] += 1
        by_src[key][1] += s["email"] in reg_set
    src_rows, src_pg = paged(sorted(by_src.items(), key=lambda kv: (-kv[1][0], kv[0])), "ps", "sources")
    src_html = ('<table><tr><th>来源</th><th class="n">来过</th><th class="n">已注册</th></tr>' + "".join(
        f'<tr><td>{_e(k) if k else "<span class=dim>直接访问 / 未知</span>"}</td><td class="n">{v[0]}</td>'
        f'<td class="n">{v[1]}</td></tr>' for k, v in src_rows) + '</table>' + src_pg +
                '<p class="foot">登录（含被拦）时记一次，只记最初的来源：utm_source · utm_campaign，没有就记来源网站域名。'
                '记录来源这个功能上线前就来过的人不在表里。</p>'
                if by_src else '<p class="empty">还没有来源记录</p>')

    # ---- 额度申请：同样一整张表一个表单 ----
    def req_row(r: dict) -> str:
        bal = (r["credit_usd"] or 0) - (r["spent_usd"] or 0)
        who = (f'<td>{_e(mask(r["email"]))}<br><span class="dim">{_t(r["at"], tz)} · 余额 {_usd(bal)} · '
               f'已花 ${r["spent_usd"] or 0:.2f}</span></td><td class="fb">{_e(r["message"][:1200])}</td>')
        if r["status"] != "pending":
            done = (f'<span class="pill ok">已批 ${r["amount_usd"]:g}</span>' if r["status"] == "approved"
                    else '<span class="pill">未批准</span>')
            return (f'<tr><td class="ck"></td>{who}<td style="white-space:nowrap">{done} '
                    f'<span class="dim">{_t(r["decided_at"], tz)}</span></td></tr>')
        i = r["id"]
        return (f'<tr><td class="ck"><input type="checkbox" name="sel" value="{i}" aria-label="选中"></td>{who}'
                f'<td style="white-space:nowrap"><span class="inl">'
                f'<input class="usd" name="usd_{i}" type="number" step="0.5" min="0.5" max="100" value="5" aria-label="美元">'
                f'<button class="tbtn go" name="act" value="approve:{i}">批准</button>'
                f'<button class="tbtn" name="act" value="decline:{i}">不批</button></span></td></tr>')

    shown_reqs = [r for r in reqs if hit(r["email"])]
    page_reqs, p, n = _slice(shown_reqs, "pr", params)
    n_pend = sum(1 for r in shown_reqs if r["status"] == "pending")
    req_html = (f'<form class="bulk" method="post" action="/_gw/admin/requests" data-total="{n_pend}">' + ret +
                '<input type="hidden" name="all" value="">' +
                ('<div class="bulkbar"><span class="seln"></span>'
                 f'<button type="button" class="tbtn allbtn" hidden>选中全部 {n_pend} 条待批（含其他页）</button>'
                 '<input class="usd" name="usd" type="number" step="0.5" min="0.5" max="100" value="5" aria-label="每人美元">'
                 '<button class="tbtn go bulkbtn" name="act" value="approve">每人这么多，批准选中的</button>'
                 '<button class="tbtn bulkbtn" name="act" value="decline">不批选中的</button></div>'
                 if any(r["status"] == "pending" for r in page_reqs) else "") +
                '<table><tr><th class="ck">' + ('<input type="checkbox" class="all" aria-label="全选本页待批">'
                                                if any(r["status"] == "pending" for r in page_reqs) else "") +
                '</th><th>谁</th><th>写了什么</th><th></th></tr>'
                + "".join(req_row(r) for r in page_reqs) + '</table></form>'
                + _pager("pr", p, n, len(shown_reqs), params, "requests")
                if shown_reqs else '<p class="empty">没有额度申请</p>')

    # ---- 反馈 / 发放 ----
    page_fb, p, n = _slice(snap["feedback"], "pf", params)
    fb_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(f["at"], tz)}</td><td>{_e(mask(f["email"]))}<br><span class="dim">{_e(f["page"])}</span></td>'
        f'<td class="fb">{_e(f["message"][:600])}</td><td class="dim">{"✉" if f["emailed"] else "·"}</td></tr>'
        for f in page_fb) + '</table>' + _pager("pf", p, n, len(snap["feedback"]), params, "feedback")
              if snap["feedback"] else '<p class="empty">还没有反馈</p>')
    gr_rows, gr_pg = paged(snap["grants"], "pg", "grants")
    gr_html = ('<table>' + "".join(
        f'<tr><td class="dim">{_t(g["at"], tz)}</td><td>{_e(mask(g["email"]))}</td>'
        f'<td class="n">${g["amount_usd"]:.2f}</td><td class="dim">{_e(g["reason"])}</td></tr>'
        for g in gr_rows) + '</table>' + gr_pg if snap["grants"] else '<p class="empty">没有发放记录</p>')

    # ---- 地理分布：每人只有最新一条地点；按城市聚成圈，按国家 / 城市排行 ----
    reg_set = {u["email"] for u in users}
    wl_set = {w["email"] for w in snap["waitlist"]}
    inv_set = {i["email"] for i in snap["pending_invites"]}

    def kind(e: str) -> str | None:
        return "reg" if e in reg_set else "wl" if e in wl_set else "inv" if e in inv_set else None
    cities: dict[tuple, dict] = {}
    countries: dict[str, dict] = {}
    located = 0
    for e, g in geo.items():
        k = kind(e)
        if k is None:
            continue
        cn = g["country_name"] or ("未知（内网 / 查不到）" if not g["country"] else g["country"])
        c = countries.setdefault(cn, {"reg": 0, "wl": 0, "inv": 0})
        c[k] += 1
        if g["lat"] is None or g["lon"] is None:
            continue
        located += 1
        key = (g["city"] or g["region"] or cn, cn)
        pt = cities.setdefault(key, {"label": " · ".join(x for x in key if x), "city": key[0], "country": cn,
                                     "region": g["region"] or "", "lat": 0.0, "lon": 0.0,
                                     "n": 0, "reg": 0, "wl": 0, "inv": 0})
        pt["lat"] += g["lat"]; pt["lon"] += g["lon"]; pt["n"] += 1; pt[k] += 1
    pts = [{**v, "lat": round(v["lat"] / v["n"], 3), "lon": round(v["lon"] / v["n"], 3)} for v in cities.values()]
    tot = lambda c: c["reg"] + c["wl"] + c["inv"]                                                  # noqa: E731
    ctop = sorted(countries.items(), key=lambda kv: (-tot(kv[1]), kv[0]))
    cmax = max((tot(c) for _, c in ctop), default=1)
    all_geo = sum(tot(c) for _, c in ctop) or 1
    c_rows, c_pg = paged(ctop, "pc", "geo")
    y_rows, y_pg = paged(sorted(pts, key=lambda v: (-v["n"], v["label"])), "py", "geo")
    country_html = ('<table><tr><th>国家 / 地区</th><th class="n">已注册</th><th class="n">被拦 / 待登录</th>'
                    '<th class="n">合计</th></tr>' + "".join(
                        f'<tr><td>{_e(name)}</td><td class="n">{c["reg"]}</td><td class="n">{c["wl"] + c["inv"]}</td>'
                        f'<td class="n">{tot(c)} <span class="dim">{tot(c) / all_geo * 100:.0f}%</span>'
                        f'<span class="share"><i style="width:{tot(c) / cmax * 100:.1f}%"></i></span></td></tr>'
                        for name, c in c_rows) + '</table>' + c_pg
                    if ctop else '<p class="empty">还没有地点记录</p>')
    city_html = ('<table><tr><th>城市</th><th>省 / 州</th><th class="n">已注册</th><th class="n">合计</th></tr>' + "".join(
        f'<tr><td>{_e(v["city"])} <span class="dim">{_e(v["country"])}</span></td><td class="dim">{_e(v["region"])}</td>'
        f'<td class="n">{v["reg"]}</td><td class="n">{v["n"]}</td></tr>'
        for v in y_rows) + '</table>' + y_pg
                 if pts else '<p class="empty">还没有地点记录</p>')
    geo_json = json.dumps(pts, ensure_ascii=False).replace("</", "<\\/")
    geo_html = (f'<div class="legend"><span><i class="a"></i>已注册</span><span><i class="c"></i>被拦 / 待登录</span>'
                f'<span>圈的面积 = 该城市人数 · 滚轮或按钮缩放，拖动平移</span></div>'
                f'<div class="map" id="geomap"><div class="msg">地图加载中…</div>'
                f'<div class="zb"><button class="tbtn zin" type="button" aria-label="放大">+</button>'
                f'<button class="tbtn zout" type="button" aria-label="缩小">−</button>'
                f'<button class="tbtn zre" type="button" aria-label="复位">⟲</button></div></div>'
                f'<script type="application/json" id="geodata">{geo_json}</script>'
                f'<div class="geo2"><div>{country_html}</div><div>{city_html}</div></div>'
                f'<p class="foot">共 {len(geo)} 人有地点记录，{located} 人能定位到城市 · 地点取自最近一次登录 / 当天首次访问的 IP，'
                f'离线库推算，城市级精度只能参考 · IP Geolocation by <a href="https://db-ip.com">DB-IP</a></p>')

    search = (f'<form class="srch" method="get" action="/_gw/admin">'
              f'<input name="q" type="search" value="{_e(q)}" placeholder="搜邮箱（用户 / 名单 / 申请）" aria-label="搜邮箱">'
              f'<button class="tbtn">搜</button>{"<a class=tbtn href=/_gw/admin>清除</a>" if q else ""}</form>')
    # 发信队列：还有几封没发、最近 24 小时用了多少额度、放弃了几封
    queued = ""
    if mail:
        full = mail["sent"] >= mail["limit"]
        queued = (f'<span class="pill{" warn" if mail["pending"] or full else ""}" title="给用户的信按每日上限慢慢发，多的顺延">'
                  f'邮件 {"待发 " + str(mail["pending"]) + " · " if mail["pending"] else ""}'
                  f'24 小时已发 {mail["sent"]}/{mail["limit"]}{"（已满，顺延）" if full and mail["pending"] else ""}'
                  f'{" · 放弃 " + str(mail["failed"]) if mail["failed"] else ""}</span>')

    body = f"""<div class="adm">
<header><a href="/"><img src="{pages.LOGO}" alt=""></a><h1>后台</h1>{queued}<span class="sp"></span>{search}
<span class="when">{_t(now, tz, "%Y-%m-%d %H:%M")} {_e(tz_name)}</span>
<button class="tbtn" onclick="jlTheme()" title="切换深浅色">{pages.icon("moon", 15)}</button>
<a class="tbtn" href="/">返回</a></header>
{f'<div class="flash">{_e(flash)}</div>' if flash else ''}
<div class="kpis">{kpi_html}</div>
<div class="card" id="requests"><h2>额度申请 <small>用户在应用里写的用途与反馈 · 批准即发额度并邮件通知 · 勾选可批量，Shift 连选</small></h2>{req_html}</div>
<div class="grid3">
<div class="card"><h2>用户增长 <small>累计 · 含被拦与已邀请 · 悬停或点按看明细</small></h2>{grow_html}</div>
<div class="card"><h2>每日活跃 <small>近 {DAYS} 天 · 悬停或点按看明细</small></h2>{act_html}</div>
<div class="card"><h2>每日 token 与花费 <small>近 {DAYS} 天 · 悬停或点按看明细</small></h2>{tok_html}</div>
</div>
<div class="card" id="geo"><h2>用户分布 <small>已注册 + 被拦 + 已邀请未登录 · 悬停或点按看明细</small></h2>{geo_html}</div>
<div class="card" id="funnel"><h2>转化漏斗 <small>{since_note}</small></h2>{funnel_html}</div>
<div class="grid2">
<div class="card" id="features"><h2>功能使用 <small>近 {DAYS} 天 · 按用过的人数排序</small></h2>{feat_html}</div>
<div class="card" id="retention"><h2>新用户回访 <small>按注册日 · 「—」= 还没到时间</small></h2>{ret_html}</div>
</div><div style="height:18px"></div>
<div class="card" id="users"><h2>用户 <small>按最近活跃排序 · 余额低于 ${low_usd:g} 标红</small></h2>{users_html}</div>
<div class="card" id="waitlist"><h2>被拦的登录 <small>邀请会给对方发邮件（排队慢慢发）· 勾选可批量，Shift 连选</small></h2>{wl_html}</div>
<div class="card" id="invites"><h2>邀请 <small>已邀请、还没登录的人</small></h2>{invite_form}{pend_html}</div>
<div class="card" id="featcost"><h2>按功能花费 <small>近 {DAYS} 天 · 引擎带来的功能标签</small></h2>{featcost_html}</div>
<div class="card" id="sources"><h2>来源 <small>用户从哪来的</small></h2>{src_html}</div>
<div class="card" id="models"><h2>按模型 <small>近 {DAYS} 天</small></h2>{model_html}</div>
<div class="card" id="errors"><h2>AI 调用失败 <small>上游限流 / 额度 / 网络 · 首次出现会邮件告警</small></h2>{err_html}</div>
<div class="card" id="feedback"><h2>最近反馈 <small>✉ = 已进每日汇总邮件</small></h2>{fb_html}</div>
<div class="card" id="grants"><h2>额度发放</h2>{gr_html}</div>
<p class="empty">这里只有账户汇总与用量元数据，不含任何用户空间里的内容。</p>
</div><script>{pages.THEME_TOGGLE_JS}{TIP_JS}{BULK_JS}</script>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js"></script>
<script>{MAP_JS}</script>"""
    return pages._doc("后台 · joblander", body, extra_css=CSS)
