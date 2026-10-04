"""网关自己的几张页面：未登录首页、开通等待页、通用提示页。

和引擎 UI 同一套色板（--accent #0E6E62），深色模式跟随系统；截图来自虚构演示数据。
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

_LIGHT = "--bg:#F6F7F8;--surface:#fff;--ink:#16191D;--ink-2:#5B636D;--ink-3:#9AA1AA;--line:#E6E8EB;" \
         "--accent:#0E7C6E;--accent-ink:#0A6156;--accent-soft:#E3F2EF;--on-accent:#fff;--sky:#EAF1FA;--runway:#3a3f44"
_DARK = "--bg:#0E1013;--surface:#15181C;--ink:#E7EAEE;--ink-2:#A2AAB4;--ink-3:#6B737D;--line:#23282E;" \
        "--accent:#2EB39F;--accent-ink:#5ACDB9;--accent-soft:#12302B;--on-accent:#05211D;--sky:#1A2636;--runway:#4a5056"
BASE_CSS = (":root{color-scheme:light;" + _LIGHT + "}"
            "@media (prefers-color-scheme: dark){:root:not([data-theme=light]){color-scheme:dark;" + _DARK + "}}"
            ":root[data-theme=dark]{color-scheme:dark;" + _DARK + "}" + """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 "Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC",sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent-ink)}
.btn{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:var(--on-accent);padding:11px 20px;
  border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;box-shadow:0 1px 2px rgba(0,0,0,.08),inset 0 1px 0 rgba(255,255,255,.15)}
.btn:hover{filter:brightness(1.06)}
.box{max-width:460px;margin:12vh auto;padding:30px 28px;background:var(--surface);border:1px solid var(--line);border-radius:16px;
  box-shadow:0 1px 2px rgba(16,24,40,.04),0 8px 28px rgba(16,24,40,.08)}
.box h1{font-size:21px;margin:0 0 8px;letter-spacing:-.01em} .box p{color:var(--ink-2);margin:0 0 16px}
table{width:100%;border-collapse:collapse;font-size:13px} td{padding:5px 0;border-bottom:1px solid var(--line)}
.tbtn{all:unset;cursor:pointer;width:32px;height:32px;display:grid;place-items:center;border-radius:8px;color:var(--ink-2);border:1px solid var(--line)}
.tbtn:hover{color:var(--ink)}
@media (max-width:520px){.box{margin:16px}}
""")

# 与引擎同一个 localStorage 键（同源），首帧前生效
THEME_HEAD = ("<script>try{var t=localStorage.getItem('jl_theme');if(t==='light'||t==='dark')"
              "document.documentElement.dataset.theme=t}catch(e){}</script>"
              '<link rel="preconnect" href="https://fonts.googleapis.com">'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">')
THEME_TOGGLE_JS = ("function jlTheme(){var r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==='dark':"
                   "matchMedia('(prefers-color-scheme: dark)').matches;var t=dark?'light':'dark';r.dataset.theme=t;"
                   "try{localStorage.setItem('jl_theme',t)}catch(e){}}")


def _doc(title: str, body: str, extra_css: str = "", head: str = "", lang: str = "zh") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{THEME_HEAD}{head}<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛬</text></svg>">
<style>{BASE_CSS}{extra_css}</style></head><body>{body}</body></html>""")


def simple(title: str, body: str, refresh: int = 0, lang: str = "zh") -> HTMLResponse:
    head = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return _doc(title, f'<div class="box">{body}</div>', head=head, lang=lang)


# ---------- 未登录首页 ----------

LANDING_CSS = """
.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
nav{display:flex;align-items:center;gap:10px;padding:18px 0}
nav b{font-size:17px;letter-spacing:-.01em}
.mark{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;font:700 14px/1 inherit;color:var(--on-accent);
  background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#3767A6))} nav .sp{flex:1} nav a.in{font-weight:600;text-decoration:none}
.hero{display:grid;grid-template-columns:1.05fr 1fr;gap:40px;align-items:center;padding:48px 0 40px}
.hero h1{font-size:44px;line-height:1.12;margin:0 0 16px;letter-spacing:-.025em;font-weight:700}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero p.lead{font-size:17px;color:var(--ink-2);margin:0 0 26px}
.hero .note{font-size:13px;color:var(--ink-3);margin-top:12px}
.shot{border-radius:14px;border:1px solid var(--line);box-shadow:0 18px 50px -20px rgba(0,0,0,.35);width:100%;display:block}
.feat{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:10px 0 44px}
.feat div{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.feat b{display:block;margin:6px 0 4px} .feat span{font-size:13.5px;color:var(--ink-2)}
.feat i{font-style:normal;font-size:22px}
.how{display:grid;grid-template-columns:1fr 1.1fr;gap:36px;align-items:center;padding:20px 0 56px}
.how ol{padding-left:20px;margin:0} .how li{margin-bottom:10px;color:var(--ink-2)} .how li b{color:var(--ink)}
footer{border-top:1px solid var(--line);padding:22px 0 40px;font-size:13px;color:var(--ink-3)}
@media (max-width:860px){.hero,.how{grid-template-columns:1fr}.feat{grid-template-columns:1fr 1fr}.hero h1{font-size:30px}}
@media (max-width:480px){.feat{grid-template-columns:1fr}}
"""


LANDING_TEXT = {
 "zh": dict(title="joblander · 求职作战室", login="登录", switch='<a href="/_gw/lang?to=en">English</a>',
   h1="把求职当成一场<br><em>有作战室的战役</em>来打",
   lead="岗位自动找上门、简历按 JD 定制、面试前有弹药、谈薪有底线——一个替你盯全局的 AI 参谋，你只负责拍板。",
   cta="用 Google 登录，开始使用 →", note="内测邀请制 · 新用户送 AI 试用额度 · 你的数据只在你自己的独立空间里",
   alt1="指挥中心：今天该做什么、什么逾期了、什么在等你批准",
   feats=[("◎", "新机会自动找", "每晚按你的偏好搜 LinkedIn 与 MyCareersFuture，对照你的履历打匹配分、初筛硬性要求。"),
          ("▤", "弹药库 → 定制简历", "上传旧简历拆成战绩库，之后每份简历都从这里取材、按 JD 重写，不编造一个字。"),
          ("♟", "面前有 brief，面后有复盘", "公司尽调、面试 brief、复盘归档，跨公司沉淀成你的应答 Playbook。"),
          ("⚖", "Offer 对比与红线", "期权按流动性折价比较；不能说的词、不能漂移的数字，系统替你守着。")],
   alt2="新机会：按匹配度排好的待决策岗位", how="三分钟上手",
   steps=[("用 Google 登录", "系统为你开一个独立空间，大约一分钟。"),
          ("上传一份旧简历", "自动拆成弹药库，并猜出你想找的岗位、替你先搜一轮。"),
          ("填目标与红线", "目标总包、不能碰的词。"),
          ("每天早上看一眼", "新机会已打好分，该跟进的已排好，点批准就行。")],
   promise="系统只起草、从不替你对外发送任何东西：每一个发出去的字都要你过目。",
   foot='joblander 是开源项目（<a href="https://github.com/Shuailong/joblander">GitHub</a>）· <a href="https://ailayoff.me">ailayoff.me</a> · 截图为虚构演示数据'),
 "en": dict(title="joblander · your job-search war room", login="Sign in", switch='<a href="/_gw/lang?to=zh">中文</a>',
   h1="Run your job search like<br><em>a campaign with a war room</em>",
   lead="Roles find you, resumes are tailored to each JD, you walk into every interview prepared and negotiate with a floor — an AI chief of staff watches the whole board, you make the calls.",
   cta="Sign in with Google →", note="Invite-only beta · free AI credit for new users · your data lives in your own private space",
   alt1="Command Center: what to do now, what is overdue, what awaits your approval",
   feats=[("◎", "Leads that find you", "Nightly searches of LinkedIn and MyCareersFuture, scored against your background with hard requirements screened."),
          ("▤", "Arsenal → tailored resumes", "Your resume becomes a bank of achievements; every tailored resume draws from it — nothing invented."),
          ("♟", "Briefs before, debriefs after", "Company research, interview briefs and debriefs that build into your personal answer playbook."),
          ("⚖", "Offers and red lines", "Equity discounted by liquidity; words you must not say and numbers that must not drift are guarded for you.")],
   alt2="New Leads: roles ranked by fit, awaiting your decision", how="Up and running in three minutes",
   steps=[("Sign in with Google", "we set up a private space for you in about a minute."),
          ("Upload an existing resume", "it becomes your Arsenal, and we guess the roles you want and run a first search."),
          ("Set targets and red lines", "your target comp and the words you never want to see."),
          ("Glance at it each morning", "new leads are scored and follow-ups lined up — just approve.")],
   promise="joblander only drafts — it never sends anything on your behalf. Every word that goes out is yours to approve.",
   foot='joblander is open source (<a href="https://github.com/Shuailong/joblander">GitHub</a>) · <a href="https://ailayoff.me">ailayoff.me</a> · screenshots use fictional demo data'),
}


def landing(lang: str = "zh") -> HTMLResponse:
    t = LANDING_TEXT["en" if lang == "en" else "zh"]
    feats = "".join(f"<div><i>{i}</i><b>{h}</b><span>{d}</span></div>" for i, h, d in t["feats"])
    steps = "".join(f"<li><b>{h}</b>——{d}</li>" if lang != "en" else f"<li><b>{h}</b> — {d}</li>"
                    for h, d in t["steps"])
    body = f"""<div class="wrap">
<nav><span class="mark">jl</span><b>joblander</b><span class="sp"></span>
  <button class="tbtn" onclick="jlTheme()" title="Theme" aria-label="Theme">◐</button>
  <span style="margin:0 16px;font-size:14px">{t['switch']}</span><a class="in" href="/auth/login">{t['login']}</a></nav>
<section class="hero">
  <div>
    <h1>{t['h1']}</h1>
    <p class="lead">{t['lead']}</p>
    <a class="btn" href="/auth/login">{t['cta']}</a>
    <div class="note">{t['note']}</div>
  </div>
  <img class="shot" src="/_gw/static/command-center.jpg" alt="{t['alt1']}">
</section>
<section class="feat">{feats}</section>
<section class="how">
  <img class="shot" src="/_gw/static/sourcing.jpg" alt="{t['alt2']}">
  <div>
    <h2 style="margin-top:0">{t['how']}</h2>
    <ol>{steps}</ol>
    <p style="color:var(--ink-3);font-size:13px;margin-top:16px">{t['promise']}</p>
  </div>
</section>
<footer>{t['foot']}</footer>
</div><script>{THEME_TOGGLE_JS}</script>"""
    return _doc(t["title"], body, LANDING_CSS, lang=lang)


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
const quips = QUIPS;
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
    if (s.status === 'ready') { document.getElementById('title').textContent = LANDED;
      setTimeout(() => location.replace('/'), 900); return; }
    document.getElementById('err').textContent = s.status === 'failed' ? RETRYING : '';
  } catch (e) {}
  setTimeout(poll, 2500);
}
poll();
"""


WAIT_TEXT = {
 "zh": dict(first="正在为你准备独立空间", again="你的空间正在重启", page="准备中 · joblander",
   steps=["分配专属存储", "启动你的引擎", "引擎热身，马上就好"],
   quips=["塔台已确认跑道，正在为你清场…", "给你的简历找停机位…", "给弹药库搬进货架…",
          "调试雷达：MCF、LinkedIn 信号就位…", "校准红线守卫…", "咖啡已经煮上了…", "最后检查起落架…"],
   landed="已着陆，欢迎登机 🛬", retrying="上一次准备没成功，正在自动重试…"),
 "en": dict(first="Setting up your private space", again="Your space is restarting", page="Getting ready · joblander",
   steps=["Allocating your storage", "Starting your engine", "Warming up — almost there"],
   quips=["Tower has cleared the runway for you…", "Finding a gate for your resume…", "Stocking the Arsenal shelves…",
          "Tuning the radar: MCF and LinkedIn signals locked…", "Calibrating the red-line guard…",
          "The coffee's on…", "Final landing-gear check…"],
   landed="Touchdown — welcome aboard 🛬", retrying="The last attempt didn't finish — retrying automatically…"),
}


def waiting(first_time: bool, lang: str = "zh") -> HTMLResponse:
    import json as _json
    t = WAIT_TEXT["en" if lang == "en" else "zh"]
    title = t["first"] if first_time else t["again"]
    steps = "".join(('<li class="cur">' if i == 0 else "<li>") + f'<span class="d"></span>{x}</li>'
                    for i, x in enumerate(t["steps"]))
    js = (f"const QUIPS = {_json.dumps(t['quips'], ensure_ascii=False)};"
          f"const LANDED = {_json.dumps(t['landed'], ensure_ascii=False)};"
          f"const RETRYING = {_json.dumps(t['retrying'], ensure_ascii=False)};" + WAIT_JS)
    body = f"""<div class="stage">
<div class="scene" aria-hidden="true">
  <span class="cloud c1">☁️</span><span class="cloud c2">☁️</span><span class="cloud c3">☁️</span>
  <div class="runway"></div><span class="puff"></span><span class="plane">🛬</span>
</div>
<h1 id="title">{title}</h1>
<div class="quip" id="quip">{t['quips'][0]}</div>
<ol class="steps">{steps}</ol>
<div class="err" id="err"></div>
<noscript><meta http-equiv="refresh" content="5"></noscript>
</div><script>{js}</script>"""
    return _doc(t["page"], body, WAIT_CSS, lang=lang)


# ---------- 网关提示文案（登录 / 邀请 / 账户 / 连接） ----------

MSG = {
 "login_failed": ("登录失败", "Sign-in failed"),
 "state_expired": ("登录状态过期，请重试。", "Your sign-in session expired — please try again."),
 "google_refused": ("Google 没有确认这次登录，请重试。", "Google didn't confirm this sign-in — please try again."),
 "unverified": ("这个 Google 账号的邮箱未验证。", "This Google account's email isn't verified."),
 "relogin": ("重新登录", "Sign in again"),
 "beta": ("还在内测", "Invite-only beta"),
 "not_invited": ("{email} 还不在邀请名单里。找把你拉进来的朋友加一下，再回来登录。",
                 "{email} isn't on the invite list yet. Ask the friend who sent you here to add you, then sign in again."),
 "account": ("账户", "Account"),
 "balance": ("AI 额度余额：<b>${bal}</b>（累计 ${credit}，已用 ${spent}）",
             "AI credit balance: <b>${bal}</b> (granted ${credit}, used ${spent})"),
 "no_usage": ("还没有用量", "No usage yet"),
 "back": ("← 返回", "← Back"),
 "logout": ("退出登录", "Sign out"),
 "unreachable_t": ("暂时连不上", "Temporarily unavailable"),
 "unreachable": ("<h1>你的空间暂时没响应</h1><p>可能正在重启，几秒后自动重试。</p>",
                 "<h1>Your space isn't responding</h1><p>It may be restarting — retrying in a few seconds.</p>"),
}


def msg(key: str, lang: str, **kw) -> str:
    zh, en = MSG[key]
    return (en if lang == "en" else zh).format(**kw)


def lang_of(cookie: str | None, accept_language: str | None) -> str:
    if cookie in ("zh", "en"):
        return cookie
    first = (accept_language or "").split(",")[0].strip().lower()
    return "en" if first.startswith("en") else "zh"
