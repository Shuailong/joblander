"""网关自己的几张页面：未登录首页（登录页）、开通等待页、通用提示页。

与引擎 UI 同一套设计 token：暖灰阶 + 深青品牌面 + 薄荷高光；深色跟随系统或侧栏手动切换
（同源 localStorage 键 jl_theme）。首页截图来自虚构演示数据，按主题与语言各一套。
"""

from __future__ import annotations

import html as _html

from fastapi.responses import HTMLResponse

_LIGHT = ("--bg:#F4F6F3;--surface:#fff;--surface-2:#F9FAF8;--ink:#16201B;--ink-2:#56625B;--ink-3:#919B95;"
          "--line:#E3E8E2;--line-strong:#D0D8D0;--accent:#0C7A68;--accent-ink:#09604F;--accent-soft:#E1F2EC;"
          "--on-accent:#fff;--brand-bg:#0F2724;--brand-bg-2:#1B3F38;--mint:#7DE3C3;--red:#C2453A;"
          "--shadow-lg:0 30px 80px rgba(20,40,30,.10),0 2px 6px rgba(20,40,30,.05)")
_DARK = ("--bg:#0A0E0D;--surface:#111816;--surface-2:#151D1A;--ink:#E5ECE8;--ink-2:#A0ACA5;--ink-3:#66726B;"
         "--line:#1E2825;--line-strong:#2B3632;--accent:#3DC9A6;--accent-ink:#72DDC2;--accent-soft:#0F2E27;"
         "--on-accent:#04201A;--brand-bg:#0B1A18;--brand-bg-2:#143029;--red:#EC7D72;"
         "--shadow-lg:0 30px 80px rgba(0,0,0,.5)")
BASE_CSS = (":root{color-scheme:light;" + _LIGHT + "}"
            "@media (prefers-color-scheme: dark){:root:not([data-theme=light]){color-scheme:dark;" + _DARK + "}}"
            ":root[data-theme=dark]{color-scheme:dark;" + _DARK + "}" + """
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 "Geist","Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC",sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent-ink)}
svg.i{flex:none}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--accent);color:var(--on-accent);padding:10px 18px;
  border-radius:10px;text-decoration:none;font-weight:600;font-size:14.5px;border:0;cursor:pointer}
.btn:hover{filter:brightness(1.06)}
.box{max-width:460px;margin:12vh auto;padding:32px 30px;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow-lg)}
.box h1{font-size:22px;margin:0 0 8px;letter-spacing:-.015em;font-weight:650} .box p{color:var(--ink-2);margin:0 0 16px}
.box .logo{width:34px;height:34px;border-radius:9px;display:block;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:13px} td{padding:6px 0;border-bottom:1px solid var(--line)}
.tbtn{all:unset;cursor:pointer;height:30px;min-width:30px;padding:0 9px;box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;
  gap:6px;border-radius:8px;color:var(--ink-2);border:1px solid var(--line);font-size:12.5px;font-weight:500;text-decoration:none;background:var(--surface)}
.tbtn:hover{color:var(--ink);border-color:var(--line-strong)}
@media (max-width:520px){.box{margin:16px;padding:26px 22px}}
""")

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&display=swap">')
# 与引擎同一个 localStorage 键（同源），首帧前生效
THEME_HEAD = ("<script>try{var t=localStorage.getItem('jl_theme');if(t==='light'||t==='dark')"
              "document.documentElement.dataset.theme=t}catch(e){}</script>" + FONTS)
THEME_TOGGLE_JS = ("function jlTheme(){var r=document.documentElement,dark=r.dataset.theme?r.dataset.theme==='dark':"
                   "matchMedia('(prefers-color-scheme: dark)').matches;var t=dark?'light':'dark';r.dataset.theme=t;"
                   "try{localStorage.setItem('jl_theme',t)}catch(e){}}")
LOGO = "/_gw/static/logo.svg"

# 线性图标（Lucide 风格，ISC 许可），继承 currentColor
_PATHS = {
    "radar": '<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/>'
             '<path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/>'
             '<circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9'
              'a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
              '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "book": '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13'
            'a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
             '<path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/>'
           '<path d="m19.07 4.93-1.41 1.41"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "github": '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5'
              '-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65'
              '-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
    "plane": '<path d="M2 22h20"/><path d="M3.77 10.77 2 9l2-4.5 1.1.55c.55.28.9.84.9 1.45s.35 1.17.9 1.45L8 8.5l3-6'
             ' 1.05.53a2 2 0 0 1 1.09 1.52l.72 5.4a2 2 0 0 0 1.09 1.52l4.4 2.2c.42.22.78.55 1.01.96l.6 1.03'
             'c.49.88-.06 1.98-1.06 2.1l-1.18.15c-.47.06-.95-.02-1.37-.24L4.29 11.15a2 2 0 0 1-.52-.38Z"/>',
}
GOOGLE_G = ('<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3'
            'C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24'
            's8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0'
            ' 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2'
            'l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5'
            'H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>')


def icon(name: str, size: int = 16, width: float = 1.9) -> str:
    return (f'<svg class="i" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_PATHS[name]}</svg>')


def _doc(title: str, body: str, extra_css: str = "", head: str = "", lang: str = "zh") -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{THEME_HEAD}{head}<title>{title}</title>
<link rel="icon" href="{LOGO}" type="image/svg+xml">
<style>{BASE_CSS}{extra_css}</style></head><body>{body}</body></html>""")


def simple(title: str, body: str, refresh: int = 0, lang: str = "zh") -> HTMLResponse:
    head = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return _doc(title, f'<div class="box"><a href="/"><img class="logo" src="{LOGO}" alt="joblander"></a>{body}</div>',
                head=head, lang=lang)


# ---------- 未登录首页：左品牌主视觉 + 右登录卡，下方是产品截图 ----------

LANDING_CSS = """
.signin{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,1fr);min-height:100vh}
.hero{position:relative;color:#E8F2EE;padding:36px 72px 30px;display:flex;flex-direction:column;overflow:hidden;
  background:radial-gradient(ellipse at 12% 8%,var(--brand-bg-2) 0,transparent 48%),
             radial-gradient(ellipse at 95% 100%,color-mix(in srgb,var(--brand-bg-2) 70%,transparent) 0,transparent 52%),var(--brand-bg)}
.hero:after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;
  background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);
  background-size:44px 44px;mask-image:radial-gradient(ellipse at 30% 30%,#000 0,transparent 70%)}
.hero>*{position:relative;z-index:1}
.brand{display:flex;align-items:center;gap:11px;color:#fff;text-decoration:none;font-weight:650;font-size:19px;letter-spacing:-.02em}
.brand img{width:32px;height:32px;border-radius:9px;box-shadow:0 4px 18px rgba(125,227,195,.25)}
.brand i{font-style:normal;color:var(--mint)}
.pitch{margin:auto 0;padding:36px 0 28px;max-width:600px}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--mint);margin-bottom:16px}
.pitch h1{font-size:44px;line-height:1.1;letter-spacing:-.025em;font-weight:650;margin:0 0 18px;color:#fff}
.pitch .lead{font-size:15.5px;line-height:1.65;color:rgba(232,242,238,.68);margin:0 0 30px;max-width:540px}
.feats{display:grid;grid-template-columns:1fr 1fr;gap:20px 28px;margin-bottom:32px}
.feat{display:flex;gap:13px}
.feat .ic{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;flex:none;color:var(--mint);
  background:rgba(125,227,195,.08);border:1px solid rgba(125,227,195,.2)}
.feat b{display:block;color:#fff;font-size:14px;font-weight:600;margin:1px 0 3px}
.feat span{font-size:13px;line-height:1.5;color:rgba(232,242,238,.58)}
.preview{max-width:440px;border-radius:16px;padding:18px 20px 16px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);
  box-shadow:0 30px 60px rgba(0,0,0,.28);backdrop-filter:blur(6px)}
.preview .hd{display:flex;align-items:center;justify-content:space-between;font-size:11px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:rgba(232,242,238,.6);margin-bottom:12px}
.preview .tag{font-size:10.5px;letter-spacing:.02em;text-transform:none;color:#0B3B34;background:var(--mint);border-radius:999px;padding:2px 9px}
.lead-row{display:flex;align-items:center;gap:12px;padding:7px 0;border-top:1px solid rgba(255,255,255,.07)}
.lead-row:first-of-type{border-top:0}
.lead-row .fit{font:600 12px/1 "Geist",sans-serif;width:38px;height:24px;border-radius:7px;display:grid;place-items:center;flex:none;
  color:#0B3B34;background:var(--mint)}
.lead-row .fit.f4{background:rgba(125,227,195,.55)}.lead-row .fit.f3{background:rgba(255,255,255,.14);color:#E8F2EE}
.lead-row b{display:block;font-size:13.5px;font-weight:600;color:#fff;line-height:1.3}
.lead-row span{font-size:12px;color:rgba(232,242,238,.55)}
.stats{display:flex;gap:26px;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.07)}
.stats div{font-size:11.5px;color:rgba(232,242,238,.55)} .stats b{display:block;font-size:18px;color:#fff;font-weight:650;letter-spacing:-.01em}
html[lang=zh] .eyebrow{letter-spacing:.2em}
.hero .fine{font-size:12.5px;color:rgba(232,242,238,.45)} .hero .fine a{color:rgba(232,242,238,.7)}
.side{display:grid;place-items:center;padding:40px 28px;background:var(--bg)}
.card{width:100%;max-width:410px;background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:26px 32px 26px;box-shadow:var(--shadow-lg)}
.card .top{display:flex;justify-content:flex-end;gap:8px;margin-bottom:38px}
.card h2{font-size:26px;font-weight:650;letter-spacing:-.02em;margin:0 0 6px}
.card .sub{color:var(--ink-2);font-size:14.5px;margin:0 0 26px}
.gbtn{display:flex;align-items:center;justify-content:center;gap:11px;height:48px;border-radius:11px;border:1px solid var(--line-strong);
  background:var(--surface);color:var(--ink);font-weight:600;font-size:15px;text-decoration:none;transition:background .15s,border-color .15s,box-shadow .15s}
.gbtn:hover{background:var(--surface-2);border-color:var(--ink-3);box-shadow:0 2px 10px rgba(0,0,0,.06)}
.mcta{display:none}
.invite{margin:14px 0 0;font-size:12.5px;color:var(--ink-3);text-align:center;line-height:1.55}
.card hr{border:0;border-top:1px solid var(--line);margin:24px 0 18px}
.checks{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:11px}
.checks li{display:flex;gap:11px;align-items:flex-start;font-size:13.5px;color:var(--ink-2);line-height:1.45}
.checks .ck{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--accent-soft);color:var(--accent);margin-top:-1px}
.card .foot{display:flex;justify-content:center;gap:18px;margin-top:22px;font-size:13px}
.card .foot a{display:inline-flex;align-items:center;gap:6px;color:var(--ink-3);text-decoration:none} .card .foot a:hover{color:var(--ink)}
.inside{max-width:1180px;margin:0 auto;padding:90px 28px 40px}
.inside .eyebrow{color:var(--accent);text-align:center;margin-bottom:10px}
.inside h2{text-align:center;font-size:32px;letter-spacing:-.022em;font-weight:650;margin:0 0 10px}
.inside .lead{text-align:center;color:var(--ink-2);max-width:620px;margin:0 auto 48px;font-size:15.5px}
.shot{margin:0 0 64px}
.shot figcaption{display:flex;gap:14px;align-items:baseline;max-width:820px;margin:0 auto 18px;text-align:center;justify-content:center;flex-wrap:wrap}
.shot figcaption b{font-size:17px;letter-spacing:-.01em} .shot figcaption span{color:var(--ink-2);font-size:14.5px}
.frame{border-radius:14px;overflow:hidden;border:1px solid var(--line);box-shadow:var(--shadow-lg);background:var(--surface)}
.frame .bar{height:30px;display:flex;align-items:center;gap:6px;padding:0 12px;border-bottom:1px solid var(--line);background:var(--surface-2)}
.frame .bar i{width:9px;height:9px;border-radius:50%;background:var(--line-strong)}
.frame img{display:block;width:100%;height:auto}
.frame img.dk{display:none}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]) .frame img.lt{display:none}:root:not([data-theme=light]) .frame img.dk{display:block}}
:root[data-theme=dark] .frame img.lt{display:none} :root[data-theme=dark] .frame img.dk{display:block}
footer{border-top:1px solid var(--line);padding:24px 28px 40px;text-align:center;font-size:13px;color:var(--ink-3)}
@media (max-width:1100px){.hero{padding:36px 40px}.pitch h1{font-size:38px}}
@media (max-width:900px){.signin{grid-template-columns:1fr}.hero{padding:28px 22px 34px}.pitch{padding:36px 0 8px}
  .pitch h1{font-size:32px}.feats{grid-template-columns:1fr;gap:16px}.preview,.hero .fine{display:none}
  .mcta{display:flex;margin:-8px 0 30px;border:0;background:#fff;color:#16201B}
  .side{padding:28px 16px 8px}.card{padding:22px 22px}.card .top{margin-bottom:20px}.inside{padding:56px 16px 20px}.inside h2{font-size:26px}}
"""

LANDING_TEXT = {
 "zh": dict(title="joblander · 求职作战室", switch=("en", "English"),
   eyebrow="求职作战室 · 你的 AI 参谋", h1="把求职当成一场<br>有作战室的战役",
   lead="岗位自动找上门、简历按 JD 定制、面试前有弹药、谈薪有底线——AI 参谋替你盯全局，你只负责拍板。",
   feats=[("radar", "新机会自动找", "每晚搜 LinkedIn 与 MyCareersFuture，按你的履历打匹配分。"),
          ("layers", "弹药库 → 定制简历", "旧简历拆成战绩库，每份简历按 JD 重写，不编造一个字。"),
          ("book", "面前 brief，面后复盘", "公司尽调、面试 brief、复盘，沉淀成你的应答 Playbook。"),
          ("scale", "Offer 对比与红线", "期权按流动性折价比较；不能说的词，系统替你守着。")],
   pv_hd="新机会 · 今晨", pv_tag="示例", pv_rows=[("5/5", "Senior PM, Cross-border", "Atlas Remit · LinkedIn"),
                                                ("4/5", "Lead PM, Card Issuing", "Pinecrest Bank · MCF"),
                                                ("3/5", "PM, Claims Automation", "Northwind Insure · MCF")],
   pv_stats=[("8", "活跃战线"), ("3", "本周面试"), ("1", "Offer")],
   fine='开源项目 · <a href="https://github.com/Shuailong/joblander">GitHub</a> · <a href="https://ailayoff.me">ailayoff.me</a>',
   welcome="欢迎", sub="登录进入你的作战室。", google="用 Google 登录",
   invite="内测邀请制：请用被邀请的 Google 账号登录。新用户送 AI 试用额度。",
   checks=["资料存在你独立的加密空间（新加坡）", "AI 经 OpenAI API 处理，不用于训练模型", "只起草、从不替你发送；随时导出或彻底删除"],
   feedback="反馈", privacy="隐私说明", theme="切换深浅色",
   in_eyebrow="看看里面", in_h2="每天早上，一眼看清整场战役", in_lead="截图来自虚构演示数据——公司、人名、数字都是编的。",
   shots=[("command-center", "指挥中心", "今天该做什么、什么逾期了、什么在等你批准。"),
          ("sourcing", "新机会", "每晚自动搜来的岗位，按匹配度排好，一键入池或否决。"),
          ("pipeline", "作战室", "每家公司在哪一关，拖一下就推进。")],
   foot='joblander 是开源项目（<a href="https://github.com/Shuailong/joblander">GitHub</a>）· <a href="/_gw/privacy">隐私说明</a> · <a href="https://ailayoff.me">ailayoff.me</a>'),
 "en": dict(title="joblander · your job-search war room", switch=("zh", "中文"),
   eyebrow="Job search · with an AI chief of staff", h1="Your job-search<br>war room",
   lead="Roles find you, resumes are tailored to each JD, you walk into every interview prepared and negotiate with a floor. The AI watches the whole board; you make the calls.",
   feats=[("radar", "Leads that find you", "Nightly LinkedIn and MyCareersFuture searches, scored against your background."),
          ("layers", "Arsenal → tailored resumes", "Your resume becomes a bank of wins; each JD gets a rewrite, nothing invented."),
          ("book", "Briefs and debriefs", "Company research, interview briefs and debriefs that build your playbook."),
          ("scale", "Offers and red lines", "Equity discounted by liquidity; words you must never say are guarded.")],
   pv_hd="New leads · this morning", pv_tag="Sample", pv_rows=[("5/5", "Senior PM, Cross-border", "Atlas Remit · LinkedIn"),
                                                              ("4/5", "Lead PM, Card Issuing", "Pinecrest Bank · MCF"),
                                                              ("3/5", "PM, Claims Automation", "Northwind Insure · MCF")],
   pv_stats=[("8", "Active"), ("3", "Interviews this week"), ("1", "Offer")],
   fine='Open source · <a href="https://github.com/Shuailong/joblander">GitHub</a> · <a href="https://ailayoff.me">ailayoff.me</a>',
   welcome="Welcome", sub="Sign in to your war room.", google="Continue with Google",
   invite="Invite-only beta: sign in with the Google account you were invited with. New users get free AI credit.",
   checks=["Stored in your own encrypted space (Singapore)", "AI via the OpenAI API — never used for training",
           "Drafts only, never sends; export or delete anytime"],
   feedback="Feedback", privacy="Privacy", theme="Toggle theme",
   in_eyebrow="A look inside", in_h2="Every morning, the whole campaign at a glance",
   in_lead="Screenshots use a fictional demo dataset — companies, people and numbers are invented.",
   shots=[("command-center", "Command Center", "What to do now, what's overdue, what's waiting for your approval."),
          ("sourcing", "New Leads", "Roles found overnight, ranked by fit — add to pipeline or reject in one click."),
          ("pipeline", "War Room", "Where every company stands; drag a card to move it forward.")],
   foot='joblander is open source (<a href="https://github.com/Shuailong/joblander">GitHub</a>) · <a href="/_gw/privacy">Privacy</a> · <a href="https://ailayoff.me">ailayoff.me</a>'),
}


def landing(lang: str = "zh") -> HTMLResponse:
    lg = "en" if lang == "en" else "zh"
    t = LANDING_TEXT[lg]
    feats = "".join(f'<div class="feat"><span class="ic">{icon(i, 18)}</span><div><b>{h}</b><span>{d}</span></div></div>'
                    for i, h, d in t["feats"])
    rows = "".join(f'<div class="lead-row"><span class="fit f{f[0]}">{f}</span><div><b>{p}</b><span>{c}</span></div></div>'
                   for f, p, c in t["pv_rows"])
    stats = "".join(f"<div><b>{n}</b>{k}</div>" for n, k in t["pv_stats"])
    checks = "".join(f'<li><span class="ck">{icon("check", 12, 2.6)}</span>{x}</li>' for x in t["checks"])
    shots = "".join(
        f'<figure class="shot"><figcaption><b>{h}</b><span>{d}</span></figcaption><div class="frame"><div class="bar"><i></i><i></i><i></i></div>'
        f'<img class="lt" src="/_gw/static/shots/{k}-{lg}-light.webp" alt="{_html.escape(h)}" loading="lazy" width="1440" height="900">'
        f'<img class="dk" src="/_gw/static/shots/{k}-{lg}-dark.webp" alt="{_html.escape(h)}" loading="lazy" width="1440" height="900">'
        f'</div></figure>' for k, h, d in t["shots"])
    to, label = t["switch"]
    gh = "https://github.com/Shuailong/joblander/issues"
    body = f"""<div class="signin">
<section class="hero">
  <a class="brand" href="/"><img src="{LOGO}" alt=""><span>joblander<i>.</i></span></a>
  <div class="pitch">
    <div class="eyebrow">{t['eyebrow']}</div>
    <h1>{t['h1']}</h1>
    <p class="lead">{t['lead']}</p>
    <a class="gbtn mcta" href="/auth/login">{GOOGLE_G}{t['google']}</a>
    <div class="feats">{feats}</div>
    <div class="preview" aria-hidden="true"><div class="hd">{t['pv_hd']}<span class="tag">{t['pv_tag']}</span></div>{rows}
      <div class="stats">{stats}</div></div>
  </div>
  <div class="fine">{t['fine']}</div>
</section>
<section class="side">
  <div class="card">
    <div class="top"><a class="tbtn" href="/_gw/lang?to={to}">{icon('globe', 14)}{label}</a>
      <button class="tbtn" onclick="jlTheme()" title="{t['theme']}" aria-label="{t['theme']}">{icon('moon', 14)}</button></div>
    <h2>{t['welcome']}</h2>
    <p class="sub">{t['sub']}</p>
    <a class="gbtn" href="/auth/login">{GOOGLE_G}{t['google']}</a>
    <p class="invite">{t['invite']}</p>
    <hr>
    <ul class="checks">{checks}</ul>
    <div class="foot"><a href="{gh}" target="_blank" rel="noopener">{icon('github', 14)}GitHub</a>
      <a href="/_gw/privacy">{t['privacy']}</a>
      <a href="{gh}" target="_blank" rel="noopener">{t['feedback']}</a></div>
  </div>
</section>
</div>
<section class="inside">
  <div class="eyebrow">{t['in_eyebrow']}</div>
  <h2>{t['in_h2']}</h2>
  <p class="lead">{t['in_lead']}</p>
  {shots}
</section>
<footer>{t['foot']}</footer>
<script>{THEME_TOGGLE_JS}</script>"""
    return _doc(t["title"], body, LANDING_CSS, lang=lg)


# ---------- 开通等待页：飞机进近 + 真实进度 ----------

WAIT_CSS = """
.stage{max-width:520px;margin:9vh auto 0;padding:0 16px;text-align:center}
.scene{position:relative;height:220px;border-radius:18px;overflow:hidden;box-shadow:var(--shadow-lg);
  background:radial-gradient(ellipse at 20% 0%,var(--brand-bg-2) 0,transparent 60%),var(--brand-bg)}
.scene:before{content:"";position:absolute;inset:0;opacity:.6;
  background-image:radial-gradient(rgba(255,255,255,.5) 1px,transparent 1.2px);background-size:46px 46px;background-position:10px 6px;
  mask-image:linear-gradient(#000,transparent 70%)}
.cloud{position:absolute;height:14px;border-radius:999px;background:rgba(255,255,255,.08);animation:drift linear infinite}
.cloud:before{content:"";position:absolute;left:22%;top:-9px;width:46%;height:20px;border-radius:999px;background:inherit}
.c1{top:40px;width:90px;animation-duration:14s}.c2{top:86px;width:64px;animation-duration:20s;animation-delay:-8s}
.c3{top:58px;width:48px;animation-duration:26s;animation-delay:-15s}
@keyframes drift{from{transform:translateX(560px)}to{transform:translateX(-120px)}}
.runway{position:absolute;left:0;right:0;bottom:0;height:36px;background:rgba(255,255,255,.06);border-top:1px solid rgba(255,255,255,.08)}
.runway:after{content:"";position:absolute;left:0;right:0;top:16px;height:3px;
  background:repeating-linear-gradient(90deg,var(--mint) 0 24px,transparent 24px 52px);
  animation:dash 0.9s linear infinite;opacity:.55}
@keyframes dash{to{background-position:-52px 0}}
.plane{position:absolute;left:50%;bottom:30px;margin-left:-24px;color:var(--mint);line-height:0;
  filter:drop-shadow(0 6px 14px rgba(125,227,195,.35));animation:approach 4.2s cubic-bezier(.35,.0,.25,1) infinite}

@keyframes approach{
  0%{transform:translate(-230px,-130px) rotate(-6deg);opacity:0}
  10%{opacity:1}
  62%{transform:translate(0,0) rotate(0)}
  72%{transform:translate(18px,0)}
  88%{transform:translate(40px,0);opacity:1}
  100%{transform:translate(60px,0);opacity:0}}
.puff{position:absolute;left:50%;bottom:34px;width:10px;height:10px;border-radius:50%;
  background:rgba(255,255,255,.5);opacity:0;animation:puff 4.2s infinite}
@keyframes puff{0%,60%{opacity:0;transform:scale(.4)}64%{opacity:.5}80%{opacity:0;transform:scale(2.4) translateX(-14px)}100%{opacity:0}}
h1{font-size:23px;margin:28px 0 6px;letter-spacing:-.015em;font-weight:650} .quip{color:var(--ink-2);min-height:26px;transition:opacity .4s}
.steps{list-style:none;padding:16px 20px;margin:22px auto 0;max-width:330px;text-align:left;background:var(--surface);
  border:1px solid var(--line);border-radius:14px}
.steps li{display:flex;gap:11px;align-items:center;padding:6px 0;color:var(--ink-3);font-size:14px}
.steps li .d{width:18px;height:18px;border-radius:50%;border:2px solid var(--line-strong);flex:none;display:grid;place-items:center;font-size:11px}
.steps li.done{color:var(--ink)} .steps li.done .d{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.steps li.cur{color:var(--ink);font-weight:600} .steps li.cur .d{border-color:var(--accent);border-top-color:transparent;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.err{color:var(--red);font-size:13px;margin-top:14px}
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
    plane = _PATHS["plane"].split("/>", 1)[1]          # 去掉地平线，只留机身
    body = f"""<div class="stage">
<div class="scene" aria-hidden="true">
  <span class="cloud c1"></span><span class="cloud c2"></span><span class="cloud c3"></span>
  <div class="runway"></div><span class="puff"></span>
  <span class="plane"><svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor" fill-opacity=".18" stroke="currentColor"
    stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{plane}</svg></span>
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
 "not_invited": ("{email} 还不在邀请名单里。我已经收到通知，加上后你直接回来登录就行；也可以找拉你进来的朋友催一下。",
                 "{email} isn't on the invite list yet. I've been notified — once you're added, just come back and sign in. "
                 "You can also nudge the friend who sent you here."),
 "not_invited_mail": ("{email} 还不在邀请名单里。申请我已经收到，确认邮件已发到这个邮箱；加上后会再发邮件通知你。",
                      "{email} isn't on the invite list yet. I've got your request and sent a confirmation to this address — "
                      "you'll get another email once you're in."),
 "account": ("账户", "Account"),
 "balance": ("AI 额度余额：<b>${bal}</b>（累计 ${credit}，已用 ${spent}）",
             "AI credit balance: <b>${bal}</b> (granted ${credit}, used ${spent})"),
 "no_usage": ("还没有用量", "No usage yet"),
 "back": ("← 返回", "← Back"),
 "logout": ("退出登录", "Sign out"),
 "export_acct": ("导出账户记录", "Export account records"),
 "privacy": ("隐私说明", "Privacy"),
 "unreachable_t": ("暂时连不上", "Temporarily unavailable"),
 "unreachable": ("<h1>你的空间暂时没响应</h1><p>可能正在重启，几秒后自动重试。</p>",
                 "<h1>Your space isn't responding</h1><p>It may be restarting — retrying in a few seconds.</p>"),
}


# ---------- 用量明细（账户与额度本身在应用的「设置 → 账户」里，这里只放数字） ----------

USAGE_CSS = """
.wrap{max-width:720px;margin:0 auto;padding:28px 20px 60px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:26px}
.top img{width:28px;height:28px;border-radius:8px}
.top a.back{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);text-decoration:none;font-size:13.5px}
.top a.back:hover{color:var(--ink)}
h1{font-size:24px;letter-spacing:-.02em;font-weight:650;margin:0 0 4px}
.sub{color:var(--ink-2);margin:0 0 22px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi span{display:block;font-size:12px;color:var(--ink-3)} .kpi b{font-size:22px;font-weight:650;letter-spacing:-.01em}
.meter{height:6px;border-radius:99px;background:var(--line);overflow:hidden;margin:0 0 26px}
.meter i{display:block;height:100%;background:var(--accent);border-radius:99px}
h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3);margin:0 0 8px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:6px 16px;margin-bottom:22px}
.card table td{padding:9px 0} .card tr:last-child td{border-bottom:0}
td.r{text-align:right;font-variant-numeric:tabular-nums} td.m{color:var(--ink-3)}
.empty{color:var(--ink-3);padding:14px 0;font-size:13.5px}
.links{display:flex;gap:16px;flex-wrap:wrap;font-size:13.5px}
.links a{color:var(--ink-2)} .links a:hover{color:var(--ink)}
@media (max-width:520px){.kpis{grid-template-columns:1fr 1fr}.kpi:last-child{grid-column:span 2}}
"""

USAGE_TEXT = {
 "zh": dict(title="用量明细", back="返回设置", sub="AI 生成（评分、定制简历、brief……）按实际用量扣。",
            bal="剩余", credit="累计获得", spent="已用", day="最近 30 天", calls="次数", cost="花费", empty="最近 30 天还没有用量",
            export="导出账户记录（JSON）", privacy="隐私说明", call_unit="次"),
 "en": dict(title="Usage", back="Back to settings", sub="AI generation (scoring, tailored resumes, briefs…) is charged by actual use.",
            bal="Remaining", credit="Granted", spent="Used", day="Last 30 days", calls="Calls", cost="Cost", empty="No usage in the last 30 days",
            export="Export account records (JSON)", privacy="Privacy", call_unit=""),
}


def usage_page(*, email: str, balance: float, credit: float, spent: float,
               days: list[tuple[str, int, float]], lang: str = "zh") -> HTMLResponse:
    t = USAGE_TEXT["en" if lang == "en" else "zh"]
    pct = 0 if credit <= 0 else max(0, min(100, round(balance / credit * 100)))
    rows = "".join(f'<tr><td>{d}</td><td class="r m">{n}{t["call_unit"]}</td><td class="r">${c:.2f}</td></tr>'
                   for d, n, c in days)
    body = f"""<div class="wrap">
<div class="top"><a href="/"><img src="{LOGO}" alt="joblander"></a>
  <a class="back" href="/settings#account">← {t['back']}</a></div>
<h1>{t['title']}</h1><p class="sub">{_html.escape(email)} · {t['sub']}</p>
<div class="kpis"><div class="kpi"><span>{t['bal']}</span><b>${balance:.2f}</b></div>
  <div class="kpi"><span>{t['credit']}</span><b>${credit:.2f}</b></div>
  <div class="kpi"><span>{t['spent']}</span><b>${spent:.2f}</b></div></div>
<div class="meter" title="{pct}%"><i style="width:{pct}%"></i></div>
<h2>{t['day']}</h2>
<div class="card">{f'<table>{rows}</table>' if rows else f'<div class="empty">{t["empty"]}</div>'}</div>
<div class="links"><a href="/_gw/export">{t['export']}</a><a href="/_gw/privacy">{t['privacy']}</a></div>
</div>"""
    return _doc(f"{t['title']} · joblander", body, extra_css=USAGE_CSS, lang=lang)


def msg(key: str, lang: str, **kw) -> str:
    zh, en = MSG[key]
    return (en if lang == "en" else zh).format(**kw)


def lang_of(cookie: str | None, accept_language: str | None) -> str:
    if cookie in ("zh", "en"):
        return cookie
    first = (accept_language or "").split(",")[0].strip().lower()
    return "en" if first.startswith("en") else "zh"


# ---------- 隐私说明 + 首次登录同意 ----------

PRIVACY_VERSION = "2026-10-05"

PRIVACY_CSS = """
.doc{max-width:760px;margin:0 auto;padding:40px 22px 80px}
.doc .top{display:flex;align-items:center;gap:10px;margin-bottom:28px}
.doc .top img{width:30px;height:30px;border-radius:8px}.doc .top b{font-size:17px;letter-spacing:-.02em}
.doc .top .sp{flex:1}
.doc h1{font-size:30px;letter-spacing:-.02em;font-weight:650;margin:0 0 6px}
.doc .ver{color:var(--ink-3);font-size:13px;margin-bottom:26px}
.doc .tldr{background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 25%,var(--line));border-radius:14px;padding:16px 20px;margin-bottom:30px}
.doc .tldr ul{margin:6px 0 0;padding-left:20px} .doc .tldr li{margin:3px 0}
.doc h2{font-size:18px;letter-spacing:-.01em;margin:30px 0 8px}
.doc p,.doc li{color:var(--ink-2)} .doc li b,.doc p b{color:var(--ink)}
.doc table{font-size:14px;margin:8px 0} .doc td,.doc th{padding:8px 10px 8px 0;vertical-align:top;text-align:left;border-bottom:1px solid var(--line)}
.doc th{font-size:12px;color:var(--ink-3);text-transform:uppercase;letter-spacing:.06em}
.consent{max-width:520px}
.consent ul{padding-left:20px;margin:0 0 18px} .consent li{color:var(--ink-2);margin:4px 0}
.consent label{display:flex;gap:10px;align-items:flex-start;font-size:14px;margin:6px 0 18px;cursor:pointer}
.consent input{margin-top:4px;accent-color:var(--accent)}
.consent .row{display:flex;gap:10px;align-items:center}
.consent button:disabled{opacity:.45;cursor:not-allowed}
.consent .no{color:var(--ink-3);font-size:14px}
"""

_PRIV = {
 "zh": dict(title="隐私说明 · joblander", h1="隐私说明", ver="版本 " + PRIVACY_VERSION + " · 内测阶段，非商业运营",
  tldr=["你的资料存在<b>只属于你的独立机器与加密磁盘</b>上（新加坡）。",
        "AI 处理经 <b>OpenAI API</b>：不用于训练模型，OpenAI 最多保留 30 天用于滥用监测。",
        "系统<b>只起草、从不替你对外发送</b>任何东西；不卖数据、不投广告。",
        "你可以随时<b>导出全部数据</b>或<b>彻底删除账户</b>（设置页）。"],
  body="""
<h2>谁在运营</h2>
<p>joblander 是一个开源项目（<a href="https://github.com/Shuailong/joblander">GitHub</a>），云端版由项目作者个人运营，
目前邀请制内测、不收费。下文的「我」指运营者。</p>

<h2>收集哪些数据</h2>
<ul>
<li><b>账户</b>：Google 登录只取你的<b>邮箱地址</b>（权限范围 openid + email），看不到你的邮件、日历或通讯录。</li>
<li><b>你提供的内容</b>：简历、战绩库、目标薪资与红线、公司档案、面试笔记、你贴进来的邀约或 JD。</li>
<li><b>系统生成的内容</b>：匹配评估、尽调报告、面试 brief、定制简历、日记与周报。</li>
<li><b>用量记录</b>：每次 AI 调用的模型、token 数、费用与时间（用于额度计费）。</li>
<li><b>反馈</b>：你主动提交的反馈内容、所在页面和浏览器标识。</li>
<li><b>技术日志</b>：请求时间、状态码、IP 地址，用于排障与防滥用；不记录页面路径与内容。</li>
<li><b>未受邀的登录</b>：没在邀请名单的人登录时，记下邮箱、尝试次数与时间，并通知运营者以便邀请；获邀或被清除时即删除。</li>
</ul>

<h2>存在哪里</h2>
<p>托管在 Fly.io <b>新加坡</b>区域。每个用户一台独立机器、一块<b>静态加密</b>的独立磁盘；
用户之间在网络层隔离，一个用户无法访问另一个用户的空间。账户与用量记录存在网关数据库（同区域、加密磁盘）。
平台每天自动快照磁盘，快照保留 5 天，用于故障恢复。</p>

<h2>交给谁处理</h2>
<table>
<tr><th>服务</th><th>用途</th><th>涉及的数据</th></tr>
<tr><td>Fly.io</td><td>服务器与存储</td><td>全部（存储于新加坡）</td></tr>
<tr><td>OpenAI</td><td>AI 生成与评估</td><td>处理当次任务所需的简历片段、JD、笔记。API 数据默认不用于训练；可能保留至多 30 天用于滥用监测；处理地在美国</td></tr>
<tr><td>Tavily</td><td>公司尽调的网页搜索</td><td>搜索词（公司名、岗位关键词），不含你的简历</td></tr>
<tr><td>Google</td><td>登录</td><td>邮箱地址</td></tr>
<tr><td>Resend</td><td>发送服务通知邮件（申请已收到、内测已开通、额度快用完），并把反馈与登录申请转发给运营者</td><td>你的邮箱与通知内容；你提交的反馈</td></tr>
</table>
<p>LinkedIn 与 MyCareersFuture 只用于读取<b>公开</b>岗位信息，不会把你的任何数据发给它们。</p>

<h2>不做什么</h2>
<ul>
<li>不出售、不出租你的数据，不做广告。</li>
<li>不用你的数据训练模型。</li>
<li>不替你对外发送任何邮件或消息——每一个发出去的字都由你自己发。</li>
<li>不要求、也不保存任何邮箱密码、银行或招聘网站登录。</li>
</ul>

<h2>运营者能看到什么</h2>
<p>作为服务器管理员，我在技术上<b>能够</b>访问存储你数据的机器。我的承诺：<b>不查看你的内容</b>；
只在你为排障明确请求并同意时，或法律要求时才访问，并告知你。账户与用量汇总（邮箱、额度、花费）我会看到，用于运营。</p>

<h2>你的权利</h2>
<ul>
<li><b>查看与更正</b>：所有内容都在界面里，可直接修改。</li>
<li><b>导出</b>：设置页「导出我的全部数据」——你空间里的全部文件打包下载，外加账户与用量记录。</li>
<li><b>重置</b>：清空空间、保留账户，重新开始。</li>
<li><b>彻底删除</b>：设置页「删除账户」——立即销毁你的机器与磁盘，并删除网关里的账户、用量、反馈与邀请记录。
平台快照在至多 5 天内过期删除；OpenAI 侧至多 30 天。删除后无法恢复。</li>
<li><b>撤回同意</b>：等同于删除账户。</li>
</ul>

<h2>关于你记录的他人信息</h2>
<p>面试笔记里可能出现招聘方、面试官的姓名等信息。请只记录求职所需的内容；这些信息与你的其他数据同等保护，并随删除一并清除。</p>

<h2>安全措施</h2>
<ul>
<li>全程 HTTPS；会话 cookie 签名、仅 HTTPS、不可被脚本读取。</li>
<li>每台用户机器只接受网关带专属口令的请求；用户机器没有公网入口。</li>
<li>磁盘静态加密；AI 调用经计量代理，用户机器上不保存真实的 OpenAI 密钥。</li>
<li>访问日志不记录页面路径与内容。</li>
</ul>

<h2>数据泄露</h2>
<p>如发生可能影响你的安全事件，我会尽快通知受影响的用户，并按适用法律（如新加坡 PDPA）向主管机关报告。</p>

<h2>联系与变更</h2>
<p>问题或请求：登录后用侧栏「反馈」，或在 <a href="https://github.com/Shuailong/joblander/issues">GitHub Issues</a> 留言（勿在公开 issue 里贴个人信息）。
本说明如有实质变更，会在你下次登录时请你重新确认。</p>
"""),
 "en": dict(title="Privacy · joblander", h1="Privacy notice", ver="Version " + PRIVACY_VERSION + " · invite-only beta, non-commercial",
  tldr=["Your data lives on <b>a machine and encrypted disk of your own</b> (Singapore).",
        "AI processing goes through the <b>OpenAI API</b>: not used for training; OpenAI may keep it up to 30 days for abuse monitoring.",
        "joblander <b>only drafts — it never sends anything on your behalf</b>. No selling data, no ads.",
        "You can <b>export everything</b> or <b>delete your account completely</b> at any time (Settings)."],
  body="""
<h2>Who runs this</h2>
<p>joblander is open source (<a href="https://github.com/Shuailong/joblander">GitHub</a>). The cloud version is run personally by the
project's author as a free, invite-only beta. "I" below means the operator.</p>

<h2>What is collected</h2>
<ul>
<li><b>Account</b>: Google sign-in only shares your <b>email address</b> (scopes openid + email) — not your mail, calendar or contacts.</li>
<li><b>What you provide</b>: resume, achievement bank, target pay and red lines, company files, interview notes, invitations or JDs you paste.</li>
<li><b>What the system generates</b>: fit assessments, research reports, interview briefs, tailored resumes, diaries and weekly reports.</li>
<li><b>Usage records</b>: model, tokens, cost and time of each AI call (for credit metering).</li>
<li><b>Feedback</b>: what you submit, the page you were on and your browser's user agent.</li>
<li><b>Technical logs</b>: request time, status code and IP address for troubleshooting and abuse prevention; page paths and content are not logged.</li>
<li><b>Uninvited sign-ins</b>: if you sign in without an invite, your email, attempt count and time are kept and the operator is notified so they can invite you; the record is deleted once you're invited or it's cleared.</li>
</ul>

<h2>Where it is stored</h2>
<p>Hosted on Fly.io in <b>Singapore</b>. Each user gets a dedicated machine and a dedicated disk <b>encrypted at rest</b>;
users are isolated at the network level and cannot reach each other's space. Account and usage records live in the gateway database
(same region, encrypted disk). The platform snapshots disks daily and keeps snapshots for 5 days for disaster recovery.</p>

<h2>Who processes it</h2>
<table>
<tr><th>Service</th><th>Purpose</th><th>Data involved</th></tr>
<tr><td>Fly.io</td><td>Servers and storage</td><td>Everything (stored in Singapore)</td></tr>
<tr><td>OpenAI</td><td>AI generation and assessment</td><td>Resume excerpts, JDs and notes needed for the task at hand. API data is not used for training by default; may be retained up to 30 days for abuse monitoring; processed in the US</td></tr>
<tr><td>Tavily</td><td>Web search for company research</td><td>Search terms (company names, role keywords) — not your resume</td></tr>
<tr><td>Google</td><td>Sign-in</td><td>Email address</td></tr>
<tr><td>Resend</td><td>Service emails to you (request received, beta access, low credit) and forwarding feedback and sign-in requests to the operator</td><td>Your email and the notice content; feedback you submit</td></tr>
</table>
<p>LinkedIn and MyCareersFuture are only used to read <b>public</b> job listings; none of your data is sent to them.</p>

<h2>What I don't do</h2>
<ul>
<li>No selling or renting your data, no advertising.</li>
<li>No training models on your data.</li>
<li>No sending emails or messages on your behalf — everything that goes out, you send yourself.</li>
<li>No asking for or storing email passwords, bank or job-site logins.</li>
</ul>

<h2>What the operator can see</h2>
<p>As the server administrator I am technically <b>able</b> to access the machine holding your data. My commitment: <b>I don't look at your content</b>.
I access it only when you explicitly ask for help troubleshooting and agree, or when the law requires it — and I'll tell you.
I do see account and usage summaries (email, credit, spend) to run the service.</p>

<h2>Your rights</h2>
<ul>
<li><b>Access and correction</b>: everything is in the interface and can be edited directly.</li>
<li><b>Export</b>: Settings → "Export all my data" downloads every file in your space, plus your account and usage records.</li>
<li><b>Reset</b>: wipe your space but keep the account, and start over.</li>
<li><b>Delete completely</b>: Settings → "Delete account" immediately destroys your machine and disk and deletes your account, usage, feedback and invite records from the gateway.
Platform snapshots expire within 5 days; OpenAI within 30 days. Deletion cannot be undone.</li>
<li><b>Withdrawing consent</b>: same as deleting your account.</li>
</ul>

<h2>Other people's information you record</h2>
<p>Interview notes may include names of recruiters or interviewers. Please record only what your job search needs; this information is protected
like the rest of your data and is erased when you delete your account.</p>

<h2>Security measures</h2>
<ul>
<li>HTTPS everywhere; session cookies are signed, HTTPS-only and not readable by scripts.</li>
<li>Each user machine only accepts gateway requests carrying its own token; user machines have no public entry point.</li>
<li>Disks encrypted at rest; AI calls go through a metering proxy, so no real OpenAI key is stored on user machines.</li>
<li>Access logs do not record page paths or content.</li>
</ul>

<h2>Breaches</h2>
<p>If a security incident may affect you, I'll notify affected users as soon as possible and report to authorities as required by applicable law (such as Singapore's PDPA).</p>

<h2>Contact and changes</h2>
<p>Questions or requests: use "Feedback" in the sidebar after signing in, or open a <a href="https://github.com/Shuailong/joblander/issues">GitHub issue</a>
(don't post personal information in public issues). If this notice changes materially, you'll be asked to confirm again at your next sign-in.</p>
"""),
}

_CONSENT = {
 "zh": dict(title="使用前请确认 · joblander", h1="使用前请确认",
   lead="开通你的空间之前，请花一分钟看一下数据怎么处理：",
   check="我已阅读并同意<a href=\"/_gw/privacy\" target=\"_blank\">隐私说明</a>",
   go="同意并继续", no="不同意，退出"),
 "en": dict(title="Before you start · joblander", h1="Before you start",
   lead="Before we set up your space, here's how your data is handled:",
   check="I have read and agree to the <a href=\"/_gw/privacy\" target=\"_blank\">privacy notice</a>",
   go="Agree and continue", no="Decline and sign out"),
}


def privacy(lang: str = "zh") -> HTMLResponse:
    lg = "en" if lang == "en" else "zh"
    t = _PRIV[lg]
    to, label = ("zh", "中文") if lg == "en" else ("en", "English")
    tldr = "".join(f"<li>{x}</li>" for x in t["tldr"])
    body = f"""<div class="doc">
<div class="top"><a href="/"><img src="{LOGO}" alt=""></a><b>joblander</b><span class="sp"></span>
  <a class="tbtn" href="/_gw/privacy?lang={to}">{icon('globe', 14)}{label}</a>
  <button class="tbtn" onclick="jlTheme()" aria-label="Theme">{icon('moon', 14)}</button></div>
<h1>{t['h1']}</h1><div class="ver">{t['ver']}</div>
<div class="tldr"><ul>{tldr}</ul></div>
{t['body']}
</div><script>{THEME_TOGGLE_JS}</script>"""
    return _doc(t["title"], body, PRIVACY_CSS, lang=lg)


def consent(lang: str = "zh") -> HTMLResponse:
    lg = "en" if lang == "en" else "zh"
    t, p = _CONSENT[lg], _PRIV[lg]
    pts = "".join(f"<li>{x}</li>" for x in p["tldr"])
    body = f"""<div class="box consent"><img class="logo" src="{LOGO}" alt="">
<h1>{t['h1']}</h1><p>{t['lead']}</p><ul>{pts}</ul>
<form method="post" action="/_gw/consent">
  <label><input type="checkbox" id="ok" onchange="document.getElementById('go').disabled=!this.checked">
    <span>{t['check']}</span></label>
  <div class="row"><button class="btn" id="go" disabled>{t['go']}</button>
    <a class="no" href="/auth/logout">{t['no']}</a></div>
</form></div>"""
    return _doc(t["title"], body, PRIVACY_CSS, lang=lg)
