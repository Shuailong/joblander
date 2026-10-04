"""网关自己的几张页面：未登录首页、开通等待页、通用提示页。

和引擎 UI 同一套色板（--accent #0E6E62），深色模式跟随系统；截图来自虚构演示数据。
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

BASE_CSS = """
:root{--bg:#F7F7F5;--surface:#fff;--ink:#26251E;--ink-2:#6F6D64;--ink-3:#A3A198;--line:#E8E6E1;
  --accent:#0E6E62;--accent-ink:#0A5249;--accent-soft:#E4F0EE;--sky:#EAF1F8;--runway:#3a3f44}
@media (prefers-color-scheme: dark){:root{--bg:#191A18;--surface:#20221F;--ink:#E9E8E3;--ink-2:#A5A49B;
  --ink-3:#6E6D66;--line:#31332E;--accent:#3FA294;--accent-ink:#5FBFB1;--accent-soft:#173832;--sky:#1F2A38;--runway:#4a5056}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Segoe UI",sans-serif}
a{color:var(--accent-ink)}
.btn{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;padding:10px 20px;
  border-radius:9px;text-decoration:none;font-weight:600;font-size:15px}
.btn:hover{filter:brightness(1.08)}
.box{max-width:460px;margin:12vh auto;padding:28px 24px;background:var(--surface);border:1px solid var(--line);border-radius:14px}
.box h1{font-size:20px;margin:0 0 8px} .box p{color:var(--ink-2);margin:0 0 16px}
table{width:100%;border-collapse:collapse;font-size:13px} td{padding:4px 0;border-bottom:1px solid var(--line)}
@media (max-width:520px){.box{margin:16px}}
"""


def _doc(title: str, body: str, extra_css: str = "", head: str = "") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{head}<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛬</text></svg>">
<style>{BASE_CSS}{extra_css}</style></head><body>{body}</body></html>""")


def simple(title: str, body: str, refresh: int = 0) -> HTMLResponse:
    head = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return _doc(title, f'<div class="box">{body}</div>', head=head)


# ---------- 未登录首页 ----------

LANDING_CSS = """
.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
nav{display:flex;align-items:center;gap:10px;padding:18px 0}
nav b{font-size:17px} nav .sp{flex:1} nav a.in{font-weight:600;text-decoration:none}
.hero{display:grid;grid-template-columns:1.05fr 1fr;gap:40px;align-items:center;padding:48px 0 40px}
.hero h1{font-size:40px;line-height:1.2;margin:0 0 14px;letter-spacing:-.5px}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero p.lead{font-size:17px;color:var(--ink-2);margin:0 0 26px}
.hero .note{font-size:13px;color:var(--ink-3);margin-top:12px}
.shot{border-radius:12px;border:1px solid var(--line);box-shadow:0 18px 50px -20px rgba(0,0,0,.35);width:100%;display:block}
.feat{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:10px 0 44px}
.feat div{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px}
.feat b{display:block;margin:6px 0 4px} .feat span{font-size:13.5px;color:var(--ink-2)}
.feat i{font-style:normal;font-size:22px}
.how{display:grid;grid-template-columns:1fr 1.1fr;gap:36px;align-items:center;padding:20px 0 56px}
.how ol{padding-left:20px;margin:0} .how li{margin-bottom:10px;color:var(--ink-2)} .how li b{color:var(--ink)}
footer{border-top:1px solid var(--line);padding:22px 0 40px;font-size:13px;color:var(--ink-3)}
@media (max-width:860px){.hero,.how{grid-template-columns:1fr}.feat{grid-template-columns:1fr 1fr}.hero h1{font-size:30px}}
@media (max-width:480px){.feat{grid-template-columns:1fr}}
"""


def landing() -> HTMLResponse:
    body = """<div class="wrap">
<nav><span style="font-size:20px">🛬</span><b>joblander</b><span class="sp"></span>
  <a class="in" href="/auth/login">登录</a></nav>

<section class="hero">
  <div>
    <h1>把求职当成一场<br><em>有作战室的战役</em>来打</h1>
    <p class="lead">岗位自动找上门、简历按 JD 定制、面试前有弹药、谈薪有底线——
      一个替你盯全局的 AI 参谋，你只负责拍板。</p>
    <a class="btn" href="/auth/login">用 Google 登录，开始使用 →</a>
    <div class="note">内测邀请制 · 新用户送 AI 试用额度 · 你的数据只在你自己的独立空间里</div>
  </div>
  <img class="shot" src="/_gw/static/command-center.jpg" alt="指挥中心：今天该做什么、什么逾期了、什么在等你批准">
</section>

<section class="feat">
  <div><i>◎</i><b>新机会自动找</b><span>每晚按你的偏好搜 LinkedIn 与 MyCareersFuture，对照你的履历打匹配分、初筛硬性要求。</span></div>
  <div><i>▤</i><b>弹药库 → 定制简历</b><span>上传旧简历拆成战绩库，之后每份简历都从这里取材、按 JD 重写，不编造一个字。</span></div>
  <div><i>♟</i><b>面前有 brief，面后有复盘</b><span>公司尽调、面试 brief、复盘归档，跨公司沉淀成你的应答 Playbook。</span></div>
  <div><i>⚖</i><b>Offer 对比与红线</b><span>期权按流动性折价比较；不能说的词、不能漂移的数字，系统替你守着。</span></div>
</section>

<section class="how">
  <img class="shot" src="/_gw/static/sourcing.jpg" alt="新机会：按匹配度排好的待决策岗位">
  <div>
    <h2 style="margin-top:0">三分钟上手</h2>
    <ol>
      <li><b>用 Google 登录</b>——系统为你开一个独立空间，大约一分钟。</li>
      <li><b>上传一份旧简历</b>——自动拆成弹药库，你核对补充。</li>
      <li><b>填目标与偏好</b>——想要的岗位、城市、目标总包、不能碰的红线。</li>
      <li><b>每天早上看一眼</b>——新机会已打好分，该跟进的已排好，点批准就行。</li>
    </ol>
    <p style="color:var(--ink-3);font-size:13px;margin-top:16px">系统只起草、从不替你对外发送任何东西：每一个发出去的字都要你过目。</p>
  </div>
</section>

<footer>joblander 是开源项目（<a href="https://github.com/Shuailong/joblander">GitHub</a>）·
  <a href="https://ailayoff.me">ailayoff.me</a> · 截图为虚构演示数据</footer>
</div>"""
    return _doc("joblander · 求职作战室", body, LANDING_CSS)


# ---------- 开通等待页：飞机进近 + 真实进度 ----------

WAIT_CSS = """
.stage{max-width:520px;margin:9vh auto 0;padding:0 16px;text-align:center}
.scene{position:relative;height:210px;border-radius:16px;overflow:hidden;
  background:linear-gradient(var(--sky),var(--surface));border:1px solid var(--line)}
.cloud{position:absolute;font-size:30px;opacity:.55;animation:drift linear infinite}
.c1{top:22px;animation-duration:14s}.c2{top:64px;font-size:22px;animation-duration:20s;animation-delay:-8s}
.c3{top:36px;font-size:18px;animation-duration:26s;animation-delay:-15s}
@keyframes drift{from{transform:translateX(560px)}to{transform:translateX(-80px)}}
.runway{position:absolute;left:0;right:0;bottom:0;height:34px;background:var(--runway)}
.runway:after{content:"";position:absolute;left:0;right:0;top:15px;height:4px;
  background:repeating-linear-gradient(90deg,#fff 0 26px,transparent 26px 52px);
  animation:dash 0.9s linear infinite;opacity:.85}
@keyframes dash{to{background-position:-52px 0}}
.plane{position:absolute;font-size:46px;left:50%;bottom:30px;margin-left:-23px;
  animation:approach 4.2s cubic-bezier(.35,.0,.25,1) infinite}
@keyframes approach{
  0%{transform:translate(-230px,-130px) rotate(-6deg);opacity:0}
  10%{opacity:1}
  62%{transform:translate(0,0) rotate(0)}
  72%{transform:translate(18px,0)}
  88%{transform:translate(40px,0);opacity:1}
  100%{transform:translate(60px,0);opacity:0}}
.puff{position:absolute;left:50%;bottom:30px;width:10px;height:10px;border-radius:50%;
  background:var(--ink-3);opacity:0;animation:puff 4.2s infinite}
@keyframes puff{0%,60%{opacity:0;transform:scale(.4)}64%{opacity:.5}80%{opacity:0;transform:scale(2.4) translateX(-14px)}100%{opacity:0}}
h1{font-size:22px;margin:24px 0 6px} .quip{color:var(--ink-2);min-height:26px;transition:opacity .4s}
.steps{list-style:none;padding:0;margin:22px auto 0;max-width:300px;text-align:left}
.steps li{display:flex;gap:10px;align-items:center;padding:6px 0;color:var(--ink-3)}
.steps li .d{width:18px;height:18px;border-radius:50%;border:2px solid var(--line);flex:none;display:grid;place-items:center;font-size:11px}
.steps li.done{color:var(--ink)} .steps li.done .d{background:var(--accent);border-color:var(--accent);color:#fff}
.steps li.cur{color:var(--ink);font-weight:600} .steps li.cur .d{border-color:var(--accent);border-top-color:transparent;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.err{color:#C2453A;font-size:13px;margin-top:14px}
@media (prefers-reduced-motion: reduce){.plane,.cloud,.runway:after,.puff,.steps li.cur .d{animation:none}.plane{transform:none}}
"""

WAIT_JS = """
const quips = ['塔台已确认跑道，正在为你清场…','给你的简历找停机位…','给弹药库搬进货架…',
  '调试雷达：MCF、LinkedIn 信号就位…','校准红线守卫…','咖啡已经煮上了…','最后检查起落架…'];
let qi = 0;
setInterval(() => { const q = document.getElementById('quip'); q.style.opacity = 0;
  setTimeout(() => { qi = (qi + 1) % quips.length; q.textContent = quips[qi]; q.style.opacity = 1; }, 400); }, 3200);
async function poll(){
  try {
    const s = await (await fetch('/_gw/status', {cache:'no-store'})).json();
    document.querySelectorAll('.steps li').forEach((li, i) => {
      li.className = i < s.stage ? 'done' : (i === s.stage ? 'cur' : '');
      li.querySelector('.d').textContent = i < s.stage ? '✓' : '';
    });
    if (s.status === 'ready') { document.getElementById('title').textContent = '已着陆，欢迎登机 🛬';
      setTimeout(() => location.replace('/'), 900); return; }
    document.getElementById('err').textContent = s.status === 'failed' ? '上一次准备没成功，正在自动重试…' : '';
  } catch (e) {}
  setTimeout(poll, 2500);
}
poll();
"""


def waiting(first_time: bool) -> HTMLResponse:
    title = "正在为你准备独立空间" if first_time else "你的空间正在重启"
    body = f"""<div class="stage">
<div class="scene" aria-hidden="true">
  <span class="cloud c1">☁️</span><span class="cloud c2">☁️</span><span class="cloud c3">☁️</span>
  <div class="runway"></div><span class="puff"></span><span class="plane">🛬</span>
</div>
<h1 id="title">{title}</h1>
<div class="quip" id="quip">塔台已确认跑道，正在为你清场…</div>
<ol class="steps">
  <li class="cur"><span class="d"></span>分配专属存储</li>
  <li><span class="d"></span>启动你的引擎</li>
  <li><span class="d"></span>引擎热身，马上就好</li>
</ol>
<div class="err" id="err"></div>
<noscript><meta http-equiv="refresh" content="5"></noscript>
</div><script>{WAIT_JS}</script>"""
    return _doc("准备中 · joblander", body, WAIT_CSS)
