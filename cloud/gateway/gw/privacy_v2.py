"""隐私说明 v2（GCP 形态）与「行为数据」开关的规则。Fly 形态继续用 pages.py 里的 v1。

与 v1 的差别（见技术方案「隐私分版本与 PDPA 合规」）：
- 存储：共享服务、按账户隔离并各自加密（Google Cloud 新加坡），不再是每人一台机器；
- 新增可关闭的「行为数据」：会话的 IP 与城市级位置、设备与浏览器、带时间的页面访问（页面模板）、
  操作结果与耗时——不含公司名与任何文字内容；
- 访问日志含页面路径（排障与安全，30 天，仅运维可读）；
- 同意方式是「通知 + 可关闭」：新用户注册时就看到开关；老用户确认 v2 后有 1 天退出期，期间不采集。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

VERSION = os.environ.get("PRIVACY_V2_DATE", "2026-12-01")   # 生效日：切流当天设成实际日期
GRACE_DAYS = 1                                                # 老用户的退出期（确认后这么多天才开始采集）
PURGE_DAYS = 30                                               # 关闭后多久内删掉已采集的行为数据


def effective_ts() -> float:
    return datetime.strptime(VERSION, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Singapore")).timestamp()


def analytics_allowed(user, now: float | None = None) -> bool:
    """这个人现在能不能采集行为数据。"""
    now = time.time() if now is None else now
    if getattr(user, "analytics_off", None):
        return False
    if user.privacy_version != VERSION or not user.consented_at:
        return False
    if (getattr(user, "created_at", 0) or 0) >= effective_ts():
        return True                                  # 新用户：注册时已看到开关并可当场关闭
    return now >= user.consented_at + GRACE_DAYS * 86400


def analytics_starts(user) -> float | None:
    """老用户在退出期内：几时开始采集（给设置页显示）。"""
    if getattr(user, "analytics_off", None) or not user.consented_at:
        return None
    if (getattr(user, "created_at", 0) or 0) >= effective_ts():
        return None
    return user.consented_at + GRACE_DAYS * 86400


PRIV = {
 "zh": dict(title="隐私说明 · joblander", h1="隐私说明", ver="版本 " + VERSION + " · 内测阶段，非商业运营",
  tldr=["你的资料存在 <b>Google Cloud 新加坡区</b>，<b>按账户隔离并用只属于你的密钥加密</b>，别的账户读不到。",
        "AI 处理经 <b>OpenAI API</b>：不用于训练模型，OpenAI 最多保留 30 天用于滥用监测。",
        "为了改进产品，我们记录<b>使用行为</b>（IP 与城市级位置、页面访问、操作结果，<b>不含任何你写的内容</b>）；"
        "<b>随时可以在设置里关闭</b>，关了照常使用。",
        "系统<b>只起草、从不替你对外发送</b>任何东西；不卖数据、不投广告。你可以随时<b>导出全部数据</b>或<b>彻底删除账户</b>。"],
  body="""
<h2>谁在运营</h2>
<p>joblander 是一个开源项目（<a href="https://github.com/Shuailong/joblander">GitHub</a>），云端版由项目作者个人运营，
目前邀请制内测、不收费。下文的「我」指运营者，也是本服务的数据保护负责人。</p>

<h2>收集哪些数据</h2>
<ul>
<li><b>账户</b>：Google 登录只取你的<b>邮箱地址</b>（权限范围 openid + email），看不到你的邮件、日历或通讯录。</li>
<li><b>你提供的内容</b>：简历、战绩库、目标薪资与红线、公司档案、面试笔记、你贴进来的邀约或 JD。</li>
<li><b>系统生成的内容</b>：匹配评估、尽调报告、面试 brief、定制简历、日记与周报。</li>
<li><b>用量记录</b>：每次 AI 调用的模型、token 数、费用、耗时、时间，以及是哪个功能发起的（只记功能名称，如「定制简历」，不含内容），用于额度计费与核算各功能的成本。</li>
<li><b>反馈</b>：你主动提交的反馈内容、所在页面和浏览器标识。</li>
<li><b>功能使用记录</b>：你哪天用了哪些页面和功能、用了几次（只记功能名称，不含公司名、简历或任何你写的内容）。</li>
<li><b>行为数据（可关闭）</b>：每次使用时的 IP 地址与城市级位置（由 Google 的负载均衡器按 IP 推算）、设备类型与浏览器；
带时间的页面访问（只记页面类型，如「公司档案页」，不记是哪家公司）、操作结果（成功或失败、错误码）与耗时。
<b>不含公司名、简历或任何你写的文字。</b>用于了解大家怎么用、卡在哪里，有针对性地改进产品，以及排查问题。</li>
<li><b>技术日志</b>：请求时间、页面路径、状态码与 IP，用于排障与防滥用；30 天后自动删除，只有运维可读。
网址里不会放你的邮箱、搜索词或任何登录凭据。</li>
<li><b>大致所在地</b>：最近一次登录或当天首次访问时的 IP 与据此推算的国家 / 省份 / 城市，用于看用户来自哪里。</li>
<li><b>从哪来</b>：第一次登录（含未受邀的登录）时，你是从哪个网站点过来的（只记网站域名，不记具体网址）以及链接上的推广标签（utm 参数），用于了解大家是怎么知道这里的；删除账户或清除未受邀记录时一并删除。</li>
<li><b>未受邀的登录</b>：没在邀请名单的人登录时，记下邮箱、尝试次数与时间，并通知运营者以便邀请；获邀或被清除时即删除。</li>
</ul>

<h2>行为数据怎么关</h2>
<ul>
<li>新用户：开通前的确认页上有「帮助改进产品」开关，默认打开，可以当场关掉。</li>
<li>已有用户：本说明生效后，你在确认时就能看到这个开关；<b>确认后 1 天内不采集</b>，这期间可以先关掉。</li>
<li>任何时候都可以在「设置 › 数据与隐私」里关闭。关闭后立即停止采集，已经采集的行为数据在 30 天内删除；关闭不影响任何功能。</li>
<li>去标识化的内容统计（例如大家的简历平均有多少条经历）：<b>目前不做</b>。将来如果要做，会单独征求你的同意，不会默认打开。</li>
</ul>

<h2>存在哪里</h2>
<p>托管在 Google Cloud <b>新加坡</b>区域。所有账户共享同一组服务，但数据<b>按账户隔离</b>：数据库只返回当前账户的数据，
每个账户的内容用<b>只属于该账户的密钥加密</b>（密钥本身由 Google Cloud KMS 托管的主密钥保护），较大的文件（如简历 PDF）同样加密后存放。
数据库支持恢复到 7 天内任一时刻，存储的文件保留 7 天的历史版本，用于故障与误删恢复。</p>

<h2>交给谁处理</h2>
<table>
<tr><th>服务</th><th>用途</th><th>涉及的数据</th></tr>
<tr><td>Google Cloud</td><td>服务器、数据库与存储；Google 登录</td><td>全部（存储于新加坡）；登录只涉及邮箱地址</td></tr>
<tr><td>OpenAI</td><td>AI 生成与评估</td><td>处理当次任务所需的简历片段、JD、笔记。API 数据默认不用于训练；可能保留至多 30 天用于滥用监测；处理地在美国</td></tr>
<tr><td>Tavily</td><td>公司尽调的网页搜索</td><td>搜索词（公司名、岗位关键词），不含你的简历</td></tr>
<tr><td>Resend</td><td>发送服务通知邮件，并把反馈与登录申请转给运营者</td><td>你的邮箱与通知内容；你提交的反馈</td></tr>
</table>
<p>OpenAI、Tavily、Resend 的处理地在新加坡以外；我们依据各家的数据处理协议，确保它们提供与新加坡《个人数据保护法》相当的保护。
LinkedIn 与 MyCareersFuture 只用于读取<b>公开</b>岗位信息，不会把你的任何数据发给它们。</p>

<h2>不做什么</h2>
<ul>
<li>不出售、不出租你的数据，不做广告。</li>
<li>不用你的数据训练模型。</li>
<li>不替你对外发送任何邮件或消息——每一个发出去的字都由你自己发。</li>
<li>不要求、也不保存任何邮箱密码、银行或招聘网站登录。</li>
</ul>

<h2>运营者能看到什么</h2>
<p>账户与用量汇总（邮箱、额度、花费），以及未关闭开关的用户的行为数据（可以按账户查看使用过程，只用于改进产品与排查问题）。
我<b>不查看你的内容原文</b>：只在你为排障明确请求并同意时，才在限定时间内查看相关内容，并告知你；法律要求时除外。</p>

<h2>保存多久</h2>
<table>
<tr><th>数据</th><th>保存</th></tr>
<tr><td>你的内容与账户</td><td>直到你删除账户</td></tr>
<tr><td>完整 IP 地址</td><td>90 天，之后截断（只保留城市级位置）</td></tr>
<tr><td>行为数据</td><td>13 个月，之后删除，只留不含个人标识的汇总</td></tr>
<tr><td>技术日志</td><td>30 天</td></tr>
<tr><td>已删除账户在备份里的副本</td><td>至多 7 天</td></tr>
</table>

<h2>你的权利</h2>
<ul>
<li><b>查看与更正</b>：所有内容都在界面里，可直接修改。</li>
<li><b>导出</b>：设置页「导出我的全部数据」——你空间里的全部文件打包下载，外加账户与用量记录。</li>
<li><b>关闭行为数据</b>：设置页「数据与隐私」。</li>
<li><b>重置</b>：清空空间、保留账户，重新开始。</li>
<li><b>彻底删除</b>：设置页「删除账户」——删除你空间里的全部数据与你的账户密钥，并删除账户、用量、反馈、行为数据与邀请记录。
数据库备份与存储里的历史版本至多 7 天内过期；OpenAI 侧至多 30 天。删除后无法恢复。</li>
<li><b>撤回同意</b>：对行为数据的同意随时可单独撤回（关掉开关）；对使用服务所必需的处理撤回同意，等同于删除账户。</li>
</ul>

<h2>关于你记录的他人信息</h2>
<p>面试笔记里可能出现招聘方、面试官的姓名等信息。请只记录求职所需的内容；这些信息与你的其他数据同等保护，并随删除一并清除。</p>

<h2>安全措施</h2>
<ul>
<li>全程 HTTPS；会话 cookie 签名、仅 HTTPS、不可被脚本读取；Web 应用防火墙与限流挡住常见攻击。</li>
<li>账户之间隔离：数据库行级隔离、每个账户独立加密密钥，系统每一次请求都只处理登录网关确认过的那个账户。</li>
<li>主密钥由 Google Cloud KMS 托管、不导出；运营者不持有长期密钥，管理操作留审计记录。</li>
<li>练兵场里运行的代码在单独的隔离沙箱里执行，没有任何权限、不能联网，接触不到其他数据。</li>
<li>AI 调用经计量代理，平台的 OpenAI 密钥只在代理里。</li>
</ul>

<h2>数据泄露</h2>
<p>如发生可能影响你的安全事件，我会尽快评估；属于须通报的情形时，在确认后 3 个日历日内通报新加坡个人数据保护委员会（PDPC），并尽快通知受影响的用户。</p>

<h2>联系与变更</h2>
<p>问题或请求（包括查看、更正、删除你的数据）：登录后用侧栏「反馈」，或在 <a href="https://github.com/Shuailong/joblander/issues">GitHub Issues</a> 留言（勿在公开 issue 里贴个人信息）。
本说明如有实质变更，会在你下次登录时请你重新确认。</p>
"""),
 "en": dict(title="Privacy · joblander", h1="Privacy notice", ver="Version " + VERSION + " · invite-only beta, non-commercial",
  tldr=["Your data lives in <b>Google Cloud's Singapore region</b>, <b>kept apart per account and encrypted with a key of your own</b> — "
        "no other account can read it.",
        "AI processing goes through the <b>OpenAI API</b>: not used for training; OpenAI may keep it up to 30 days for abuse monitoring.",
        "To improve the product we record <b>how the app is used</b> (IP and city-level location, page visits, outcomes of actions — "
        "<b>never anything you wrote</b>). <b>You can switch this off in Settings at any time</b> and keep using everything.",
        "joblander <b>only drafts — it never sends anything on your behalf</b>. No selling data, no ads. "
        "You can <b>export everything</b> or <b>delete your account completely</b> at any time."],
  body="""
<h2>Who runs this</h2>
<p>joblander is open source (<a href="https://github.com/Shuailong/joblander">GitHub</a>). The cloud version is run personally by the
project's author as a free, invite-only beta. "I" below means the operator, who is also the data protection officer for this service.</p>

<h2>What is collected</h2>
<ul>
<li><b>Account</b>: Google sign-in only shares your <b>email address</b> (scopes openid + email) — not your mail, calendar or contacts.</li>
<li><b>What you provide</b>: resume, achievement bank, target pay and red lines, company files, interview notes, invitations or JDs you paste.</li>
<li><b>What the system generates</b>: fit assessments, research reports, interview briefs, tailored resumes, diaries and weekly reports.</li>
<li><b>Usage records</b>: model, tokens, cost, duration and time of each AI call, and which feature made it (the feature name only, e.g. "tailor resume" — no content), for credit metering and working out what each feature costs.</li>
<li><b>Feedback</b>: what you submit, the page you were on and your browser's user agent.</li>
<li><b>Feature usage</b>: which pages and features you used on which day, and how often (feature names only — no company names, resume or anything you wrote).</li>
<li><b>Behavior data (can be switched off)</b>: the IP address and city-level location of each visit (estimated from the IP by Google's load balancer),
device type and browser; timed page visits (the page type only, e.g. "company file page" — not which company), outcomes of actions
(success or failure, error code) and how long they took. <b>No company names, resume or any text you wrote.</b> Used to understand how people use
the app and where they get stuck, to improve the product in a targeted way, and to troubleshoot.</li>
<li><b>Technical logs</b>: request time, page path, status code and IP, for troubleshooting and abuse prevention; deleted after 30 days and
readable only by operations. Your email, search terms or credentials are never put in web addresses.</li>
<li><b>Approximate location</b>: the IP of your latest sign-in or first visit of the day and the country / region / city estimated from it, to see where users come from.</li>
<li><b>Where you came from</b>: at your first sign-in (including uninvited ones), the website you came from (its domain only, not the full address) and any campaign tags on the link (utm parameters), to learn how people find this; deleted with your account or with an uninvited-sign-in record.</li>
<li><b>Uninvited sign-ins</b>: if you sign in without an invite, your email, attempt count and time are kept and the operator is notified so they can invite you; the record is deleted once you're invited or it's cleared.</li>
</ul>

<h2>Switching behavior data off</h2>
<ul>
<li>New users: the confirmation page before your space is set up has a "Help improve joblander" switch, on by default, which you can turn off right there.</li>
<li>Existing users: you see the same switch when you confirm this notice; <b>nothing is collected for a day after you confirm</b>, so you can turn it off first.</li>
<li>You can turn it off at any time under Settings › Data &amp; privacy. Collection stops immediately and behavior data already collected is deleted within 30 days; nothing else changes.</li>
<li>De-identified statistics about content (e.g. how many entries resumes have on average): <b>not done today</b>. If that ever changes, you'll be asked separately, and it won't be on by default.</li>
</ul>

<h2>Where it is stored</h2>
<p>Hosted on Google Cloud in <b>Singapore</b>. All accounts share the same services, but data is <b>kept apart per account</b>: the database only returns
the current account's data, and each account's content is <b>encrypted with a key of its own</b> (protected by a master key held in Google Cloud KMS);
larger files such as resume PDFs are encrypted the same way. The database can be restored to any point in the last 7 days and stored files keep
7 days of history, for recovering from failures and mistakes.</p>

<h2>Who processes it</h2>
<table>
<tr><th>Service</th><th>Purpose</th><th>Data involved</th></tr>
<tr><td>Google Cloud</td><td>Servers, database and storage; Google sign-in</td><td>Everything (stored in Singapore); sign-in only involves your email address</td></tr>
<tr><td>OpenAI</td><td>AI generation and assessment</td><td>Resume excerpts, JDs and notes needed for the task at hand. API data is not used for training by default; may be retained up to 30 days for abuse monitoring; processed in the US</td></tr>
<tr><td>Tavily</td><td>Web search for company research</td><td>Search terms (company names, role keywords) — not your resume</td></tr>
<tr><td>Resend</td><td>Service emails to you, and forwarding feedback and sign-in requests to the operator</td><td>Your email and the notice content; feedback you submit</td></tr>
</table>
<p>OpenAI, Tavily and Resend process data outside Singapore; under their data processing terms they provide protection comparable to Singapore's
Personal Data Protection Act. LinkedIn and MyCareersFuture are only used to read <b>public</b> job listings; none of your data is sent to them.</p>

<h2>What we don't do</h2>
<ul>
<li>We don't sell or rent your data, and there are no ads.</li>
<li>We don't train models on your data.</li>
<li>We never send emails or messages on your behalf — every word that goes out is sent by you.</li>
<li>We never ask for or store email passwords, bank logins or job-site logins.</li>
</ul>

<h2>What the operator can see</h2>
<p>Account and usage summaries (email, credit, spend), and behavior data for users who haven't switched it off (usage over time per account,
used only to improve the product and troubleshoot). I <b>don't read your content</b>: only when you ask for help with a problem and agree, for a
limited time and with you informed — or when the law requires it.</p>

<h2>How long it's kept</h2>
<table>
<tr><th>Data</th><th>Kept for</th></tr>
<tr><td>Your content and account</td><td>Until you delete your account</td></tr>
<tr><td>Full IP addresses</td><td>90 days, then truncated (city-level location only)</td></tr>
<tr><td>Behavior data</td><td>13 months, then deleted; only aggregates without personal identifiers remain</td></tr>
<tr><td>Technical logs</td><td>30 days</td></tr>
<tr><td>Copies of a deleted account in backups</td><td>Up to 7 days</td></tr>
</table>

<h2>Your rights</h2>
<ul>
<li><b>Access and correction</b>: everything is visible and editable in the app.</li>
<li><b>Export</b>: Settings › "Export all my data" downloads every file in your space as a zip, plus account and usage records.</li>
<li><b>Switch off behavior data</b>: Settings › Data &amp; privacy.</li>
<li><b>Reset</b>: clear your space but keep the account, and start over.</li>
<li><b>Delete completely</b>: Settings › "Delete account" deletes all data in your space and your account key, plus account, usage, feedback,
behavior data and invite records. Database backups and stored file history expire within 7 days; at OpenAI within 30 days. This can't be undone.</li>
<li><b>Withdraw consent</b>: consent to behavior data can be withdrawn on its own at any time (switch it off); withdrawing consent to processing
that's necessary to run the service means deleting your account.</li>
</ul>

<h2>Other people's information in your notes</h2>
<p>Interview notes may include recruiters' or interviewers' names. Please record only what your job search needs; this information is protected
like the rest of your data and deleted with it.</p>

<h2>Security</h2>
<ul>
<li>HTTPS everywhere; session cookies are signed, HTTPS-only and not readable by scripts; a web application firewall and rate limits block common attacks.</li>
<li>Accounts are kept apart: row-level isolation in the database and a separate encryption key per account; every request only touches the one account confirmed by the sign-in gateway.</li>
<li>The master key is held in Google Cloud KMS and never exported; the operator holds no long-lived keys, and admin actions are audited.</li>
<li>Code you run in Drills executes in a separate isolated sandbox with no permissions and no network access, out of reach of any other data.</li>
<li>AI calls go through a metering proxy; the platform's OpenAI key only lives in that proxy.</li>
</ul>

<h2>Data breaches</h2>
<p>If a security incident may affect you, I'll assess it promptly; where notification is required, I'll notify Singapore's Personal Data Protection
Commission (PDPC) within 3 calendar days of confirming that, and tell affected users as soon as possible.</p>

<h2>Contact and changes</h2>
<p>Questions or requests (including access to, correction or deletion of your data): use "Feedback" in the sidebar after signing in, or open a
<a href="https://github.com/Shuailong/joblander/issues">GitHub issue</a> (don't post personal information in public issues).
If this notice changes materially, you'll be asked to confirm again at your next sign-in.</p>
"""),
}

CONSENT = {
 "zh": dict(title="使用前请确认 · joblander", h1="使用前请确认",
   lead="开通或继续使用你的空间之前，请花一分钟看一下数据怎么处理：",
   check="我已阅读并同意<a href=\"/_gw/privacy\" target=\"_blank\">隐私说明</a>",
   analytics="帮助改进产品：记录我的使用行为（IP 与城市级位置、页面访问与操作结果，不含任何内容）。随时可在设置里关闭。",
   analytics_note="已有账户确认后 1 天内不采集，这期间也可以先关掉。",
   go="同意并继续", no="不同意，退出"),
 "en": dict(title="Before you start · joblander", h1="Before you start",
   lead="Before we set up or continue your space, here's how your data is handled:",
   check="I have read and agree to the <a href=\"/_gw/privacy\" target=\"_blank\">privacy notice</a>",
   analytics="Help improve joblander: record how I use the app (IP and city-level location, page visits and outcomes — never any content). "
             "You can switch this off in Settings at any time.",
   analytics_note="For existing accounts nothing is collected for a day after you confirm, so you can switch it off first.",
   go="Agree and continue", no="Decline and sign out"),
}
