"""界面英文表：键是中文原文（模板里 _() 包住的那句），值是英文。缺键回落中文。"""

EN: dict[str, str] = {' High 机会': ' high-priority leads',
 ' 和 LinkedIn': ' and LinkedIn',
 ' 失败：': ' failed: ',
 ' 完成': ' done',
 ' 家：': ' companies: ',
 ' 已写回': ' saved',
 '### X1. 项目名 —— 一句话战果&#10;- **S**：…&#10;- **T**：…&#10;- **A**：…&#10;- **R**：…': '### X1. Project — one-line '
                                                                                 'result&#10;- **S**: '
                                                                                 '…&#10;- **T**: …&#10;- '
                                                                                 '**A**: …&#10;- **R**: …',
 ')">✔ 确认入库</button></div>': ')">✔ Save to Arsenal</button></div>',
 '/ 共': '/ total',
 '03-materials 下没有 resume*.html 母版。': 'No resume*.html master in 03-materials.',
 '3 行足矣：打得好的 / 失手的 / 下次改': '3 lines is enough: what went well / what slipped / what to change',
 '<b>教练</b>：': '<b>Coach</b>: ',
 '<b>教练</b>：出错了——': '<b>Coach</b>: something went wrong — ',
 '<div class="note">📌 意见已记下——出下一版时一并执行</div>': '<div class="note">📌 Feedback noted — applied in the next '
                                               'version</div>',
 '<div class="plan">归档计划（确认后入弹药库）：': '<div class="plan">Filing plan (saved to Arsenal on confirm):',
 '<p class="note">（空）</p>': '<p class="note">(empty)</p>',
 '<span class="note">✅ 已入库：': '<span class="note">✅ Saved: ',
 'AI 的归 AI，你的判断单独留档': "AI's take stays AI's; your judgment is kept separately",
 'AI 草稿': 'AI draft',
 'AI 额度': 'AI credit',
 'AI 额度…': 'AI credit…',
 'AI 额度已用完——充值或订阅后继续使用': 'AI credit used up — top up or subscribe to continue',
 'AI 额度已用完——生成类功能暂停。<a href="/_gw/account">查看用量</a>，或找邀请你的朋友加额度。': 'AI credit used up — generation is '
                                                                   'paused. <a href="/_gw/account">See '
                                                                   'usage</a>, or ask the friend who invited '
                                                                   'you for more credit.',
 'Bar Raiser / 交叉面': 'Bar raiser / cross-team',
 'FDE 版（母版）': 'FDE (master)',
 'Gmail 上次': 'Gmail last run',
 'Gmail 邮箱': 'Gmail',
 'Google 日历': 'Google Calendar',
 'HTML 源': 'HTML source',
 'High 优先级机会': 'High-priority leads',
 'High 优先级机会（自动跟随作战室）': 'High-priority leads (follows War Room)',
 'High 战线': 'High priority',
 'Hiring Manager 轮': 'Hiring manager',
 'JD 匹配': 'JD fit',
 'JD 原文，或 https://…（选了文件这里可空）': 'JD text, or https://… (optional if you pick files)',
 'JD 已入档': 'JD saved',
 'JD 文件': 'JD files',
 'JD 语料：': 'JD corpus:',
 'JD 链接 ✎': 'JD link ✎',
 'JD 链接已清除': 'JD link cleared',
 'JD 附件（可空：PDF/文本——正文进抽取，文件随批准落公司档案）': 'JD attachment (optional: PDF/text — its text is extracted; the file '
                                       'is filed to the company on approval)',
 'LinkedIn 上次': 'LinkedIn last run',
 'LinkedIn 个人主页（供起草内推/触达时引用）': 'Your LinkedIn profile URL (used when drafting referral/outreach messages)',
 'LinkedIn 职位自动搜索': 'Automatic LinkedIn job search',
 'MCF 上次': 'MCF last run',
 'Offer': 'Offer',
 'Offer 名': 'Offer',
 'Offer 对比': 'Offers',
 'Offer 对比 · joblander': 'Offers · joblander',
 'Offer 对比（W13）': 'Offer comparison',
 'Playbook 战况：': 'Playbook record:',
 'Rejected / Terminated / Withdrawn / Not Apply——任一阶段都可能转入': 'Rejected / Terminated / Withdrawn / Not Apply '
                                                             '— can happen at any stage',
 'Scout · 跟进更新': 'Scout · follow-up update',
 'Screening · HR/猎头初筛': 'Screening · HR / recruiter',
 'Scribe · 面后录入': 'Scribe · post-interview notes',
 'Scribe 工作中…（约 30 秒）': 'Scribe is working… (~30 s)',
 'TC 折价': 'TC discounted',
 'TC 面值': 'TC face',
 'W4 · MCF 实时 band + 统计层零 LLM + 叙事层引用逐岗来源 · 数据超两周建议重跑': 'Live MCF pay bands + statistics + sourced narrative '
                                                        '· re-run if older than two weeks',
 'WhatsApp / 猎头消息 / 任意 JD': 'WhatsApp / recruiter messages / any JD',
 'bonus 保底': 'Bonus guaranteed',
 'bonus 月数': 'Bonus months',
 'e.g. 对方是 infra 背景 VP，重点讲 agent 平台的工程决策': 'e.g. the interviewer is an infra VP — focus on engineering '
                                           'decisions behind the agent platform',
 'levels.fyi / 群聊里看到的 band 情报原文……': 'Pay bands from levels.fyi / group chats…',
 'markdown：### 小节 · - 列表 · **粗体** · &gt; 引用 · | 表格 |': 'markdown: ### section · - list · **bold** · &gt; '
                                                       'quote · | table |',
 'miss——必修': 'misses in a row — must fix',
 'tracker Feedback（旧版复盘字段，已由时间线取代）': 'Tracker feedback (legacy field, replaced by the timeline)',
 'tracker 建行（线索列）+ 建公司档案': 'Creates a pipeline row and a company file',
 'vs 锚点': 'vs anchor',
 '{n} 个岗位': '{n} roles',
 '{n} 件要动': '{n} to act on',
 '{n} 单更新提案等你批（公司页/指挥中心）': '{n} update proposals awaiting your approval',
 '{n} 单等你批': '{n} awaiting approval',
 '{n} 条新线索待决策': '{n} new leads to review',
 '{p} 不存在——检查 config profile.files': '{p} not found — check profile.files in config',
 '· 上次改': '· last edited',
 '· 保存前旧版自动存 jd/.trash/ 可恢复；评估与简历下次运行吃的就是改后的版本。PDF 不可编辑——删了重传或贴原文。': '· The old version is kept in the '
                                                                     'trash; the next assessment and resume '
                                                                     "use your edit. PDFs can't be edited — "
                                                                     'delete and re-upload, or paste the '
                                                                     'text.',
 '· 数字对即两值，': '· numbers show both values,',
 '· 日报': '· daily',
 '· 旧版画像轴——重跑「评估匹配」出 JD 定制轴': '· old generic axes — re-run "Assess fit" for JD-specific axes',
 '· 邀约': '· invite',
 '— 点开调整': '— click to adjust',
 '——「无」的去公司页传 JD，重估即吃进。': ' — for "none", add a JD on the company page and re-assess.',
 '——期权按流动性折价档计入；结构确定性 &gt; 数字。锚点差距只显示百分比，不在屏幕上摆锚点数。': ' — equity is discounted by liquidity tier; certainty '
                                                      'of structure &gt; headline numbers. Gaps to your '
                                                      'anchor show as percentages only.',
 '—（点击添加）': '— (click to add)',
 '↻ 全量刷新': '↻ Refresh all',
 '↻ 扫邮箱': '↻ Scan inbox',
 '↻ 立即搜': '↻ Search now',
 '↻ 重估能力画像': '↻ Re-assess profile',
 '⌘/Ctrl + Enter 运行 · 草稿自动保存在本机': '⌘/Ctrl + Enter to run · drafts are saved in this browser',
 '⏰ Follow-up 到期（': '⏰ Follow-up due (',
 '⏱ 超时': '⏱ Timed out',
 '▤ 弹药库': '▤ Arsenal',
 '▤ 战绩素材库（achievement-bank）': '▤ Achievement bank',
 '▬ JD 要求': '▬ JD needs',
 '▬ 市场要求': '▬ Market needs',
 '▮ 当前能力': '▮ Current level',
 '▮ 我（按弹药库）': '▮ Me (per Arsenal)',
 '▶ 运行全部用例': '▶ Run all tests',
 '▸ 现在就做（按序）': '▸ Do now (in order)',
 '⚐ 在你手上？': '⚐ In your court?',
 '⚑ 在你手上': '⚑ In your court',
 '⚑ 待你': '⚑ To do',
 '⚑ 等你动手': '⚑ Your move',
 '⚙ JD 策略：': '⚙ JD scope:',
 '⚙ 新版生成中——完成自动刷新</div>': '⚙ Generating a new version — the page refreshes when done</div>',
 '⚠ 确认删除？': '⚠ Confirm delete?',
 '⚠️ 弹药库为空——初筛无履历可对照，req_gaps 全部只能标存疑。去「弹药库」页写第一段战绩。': '⚠️ Your Arsenal is empty — screening has nothing to '
                                                       'compare against. Add your first achievements on the '
                                                       'Arsenal page.',
 '⚠️ 手调过但本轮维度里没匹配上的：': "⚠️ Adjusted but not matched to this round's dimensions:",
 '⚠️ 无（点这里填）': '⚠️ None (click to add)',
 '⚠️ 未绑定附件（文件名带日期即可自动挂到当日事件）：': "⚠️ Unlinked files (put a date in the filename to attach it to that day's "
                                'event):',
 '⛔ 运行错误': '⛔ Runtime error',
 '✅ 已入库': '✅ Saved',
 '✎ 填搜索偏好': '✎ Fill in preferences',
 '✎ 核对偏好': '✎ Check preferences',
 '✎ 编辑': '✎ Edit',
 '✎ 编辑 JD': '✎ Edit JD',
 '✓ 全部通过': '✓ All passed',
 '✔ 确认入库': '✔ Save to Arsenal',
 '✗ 未通过': '✗ Failed',
 '⠿ 拖动段头把手可排序（默认顺序 = 定制简历取材的阅读序）；🗑 双击确认删除；「使用注意」规则段不受这些操作影响。': '⠿ Drag a section handle to reorder (order = '
                                                               'reading order for tailored resumes); 🗑 click '
                                                               'twice to delete; rule sections are '
                                                               'unaffected.',
 '一句话定位 ✎': 'One-line pitch ✎',
 '一句话摘要': 'One-line summary',
 '一段 = 一个公司或项目。写 STAR：情境 / 任务 / 动作 / 可验证的结果。': 'One section = one company or project. Write STAR: situation '
                                               '/ task / action / verifiable result.',
 '一行一条': 'One per line',
 '三卡': 'Cards',
 '三步把 joblander 喂到能用': 'Three steps to get joblander working for you',
 '上传一份旧简历': 'Upload an existing resume',
 '上传并生成弹药库': 'Upload and build Arsenal',
 '上传简历后系统会先猜一组目标岗位并替你搜一轮；也可以直接去填。': "Once you upload a resume we'll guess target roles and run a first "
                                    'search; or fill them in yourself.',
 '上次抓 {a} 提 {b}': 'last run: {a} fetched, {b} proposed',
 '下一步': 'Next step',
 '下一步 ✎': 'Next step ✎',
 '下一步：': 'Next step:',
 '下面这组搜索偏好是根据你的简历猜的': 'These search preferences were guessed from your resume',
 '不写入任何系统，只记账，可反悔': 'Nothing is written — only logged, reversible',
 '不能出现在对外材料里的词：内部项目代号、绩效评级、现薪数字……': 'Words that must never appear in anything you send out: internal '
                                    'codenames, performance ratings, current salary…',
 '个 offer，但换算失败——检查私有 config 的 policy（汇率/折价档）。': ' offers, but conversion failed — check policy (FX / '
                                                 'discount tiers) in your config.',
 '个附件': ' attachments',
 '事件已更新': 'Event updated',
 '事件标题': 'Event title',
 '亮点已存': 'Highlights saved',
 '人工': 'Manual',
 '人工改过：': 'Edited by you: ',
 '人工记录（通话、邮件、笔记、复盘）。面试转写要 AI 录入的，走「转写 → 录入」。': 'Manual notes (calls, emails, notes, debriefs). For '
                                               'AI-processed interview transcripts, use "Transcript → log".',
 '今天': 'Today',
 '今天 {n} 场': '{n} today',
 '今天的感受、判断、要提醒自己的话……': 'How today went, your judgment calls, reminders to yourself…',
 '今天还没有战线事件——打了仗（面试/通话/邮件落档案）之后，这里 21:30 自动出日记草稿。': 'No events today yet — once you log interviews, calls or '
                                                    'emails to a company file, a diary draft appears here at '
                                                    '21:30.',
 '今日到期': 'Due today',
 '从 Glassdoor / LinkedIn / 群聊里复制的情报原文……': 'Text copied from Glassdoor / LinkedIn / group chats…',
 '从事件移除（文件保留在未绑附件区）': 'Detach (file stays under unlinked files)',
 '从作战室删除这行；公司档案与时间线保留': 'Remove from War Room; the company file and timeline are kept',
 '从简历生成弹药库': 'Build Arsenal from resume',
 '件': '',
 '件）': ')',
 '任何生成的简历、消息草稿里出现这些词都会被拦下。': 'Any generated resume or message draft containing these words is blocked.',
 '任务': 'Task',
 '份复盘 +': ' debriefs +',
 '优先级 ⇅': 'Priority ⇅',
 '估于': 'Assessed',
 '低匹配 / 未评分（{n} 家）——大概率不值得看，展开确认后批量否决': 'Low fit / unscored ({n} companies) — probably not worth it; expand '
                                        'to confirm and reject in bulk',
 '作战室': 'War Room',
 '作战室 · joblander': 'War Room · joblander',
 '作战室排了面试，但日历接下来 7 天没这场': 'An interview is in your War Room but not on your calendar for the next 7 days',
 '作战室还没有公司。': 'No companies in War Room yet.',
 '你': 'You',
 '你写的 ｜ 附件挂在事件上': 'written by you | attachments hang off events',
 '你标记的：球在你这边': "You flagged it: ball's in your court",
 '你的材料、目标与红线，以及可选功能。': 'Your materials, targets and red lines, plus optional features.',
 '你自己的总结与感受——与 AI 生成的部分分开存放，永不被自动覆盖': 'Your own reflections — stored separately from AI content and never '
                                      'overwritten',
 '你自己的总结与感受——与 AI 生成的部分分开存放，重生成永不覆盖': 'Your own reflections — kept separate from AI content and never '
                                      'overwritten',
 '例如 250000': 'e.g. 250000',
 '例：HM 电话 / 王某': 'e.g. HM call / Jane Doe',
 '依据与缺口详情见时间线「评估快照」 · JD 或档案有更新再点「评估匹配」': "Reasons and gaps are in the timeline's assessment snapshot · "
                                          're-run "Assess fit" after JD or file updates',
 '依据（如：某场面试暴露了什么）': 'Reason (e.g. what an interview revealed)',
 '依次拉取已连接的数据源，完成后刷新页面': 'Pull each connected source, then refresh',
 '保存': 'Save',
 '保存 JD': 'Save JD',
 '保存事件': 'Save event',
 '保存偏好': 'Save preferences',
 '保存后点「↻ 重估能力画像」生效。': 'After saving, click "↻ Re-assess profile".',
 '保存复盘': 'Save debrief',
 '保存失败': 'Save failed',
 '保存并计算': 'Save and compare',
 '保存手记': 'Save notes',
 '保存策略': 'Save scope',
 '保存记录': 'Save note',
 '保底': 'Guaranteed',
 '修改求职偏好 →': 'Edit search preferences →',
 '偏好已保存——下次扫描即生效': 'Preferences saved — used from the next search',
 '做完前两步就能生成定制简历、面试 brief 和 Offer 对比。所有内容只存在你自己的空间里。': 'After the first two steps you can generate tailored '
                                                      'resumes, interview briefs and offer comparisons. '
                                                      'Everything stays in your own private space.',
 '先勾几条': 'Select some first',
 '先告诉系统你在找什么': 'First, tell us what you are looking for',
 '先在下方「搜索偏好」填目标岗位关键词': 'Fill in target job titles under "Search preferences" below first',
 '先补齐日期和时间': 'Fill in the date and time first',
 '先跳过，随便看看': 'Skip for now, just look around',
 '先选一个简历文件': 'Choose a resume file first',
 '入库': 'Added',
 '入池': 'Added to pipeline',
 '入池初筛（req_gaps 对照）、公司页「评估匹配」、能力画像读的都是弹药库——在那里改了战绩，下次评估自动生效，无需任何操作。': 'Lead screening, company fit '
                                                                      'assessment and your capability '
                                                                      'profile all read from the Arsenal — '
                                                                      'edit your achievements there and the '
                                                                      'next assessment picks them up '
                                                                      'automatically.',
 '全天': 'All day',
 '全屏阅读完整文档': 'Read full document',
 '全选': 'Select all',
 '全部': 'All',
 '公司 / 岗位': 'Company / role',
 '公司尽调（W2/W3）': 'Company research',
 '关键词': 'Keywords',
 '关键词（逗号分隔，空 = 用侦察偏好）': 'Keywords (comma-separated; empty = use your preferences)',
 '关闭': 'Closed',
 '关闭为：': 'Close as:',
 '内容': 'Content',
 '内容（markdown：### 小节 / - 列表 / **粗体** / &gt; 注记）': 'Content (markdown: ### heading / - list / **bold** / &gt; '
                                                  'note)',
 '内容（支持 markdown；从审批队列/邮件贴过来也行）': 'Content (markdown supported; paste from email is fine)',
 '内推匹配': 'Referral match',
 '内推匹配 · {co}': 'Referral match · {co}',
 '内推匹配（W14 · 入池自动）': 'Referral match (on add)',
 '内推匹配（W14）': 'Referral match',
 '内推匹配（入池自动）': 'Referral match (on add)',
 '出下一版': 'Make next version',
 '出排期建议': 'Suggest times',
 '出炉': 'Generated',
 '出调研报告（约 1-2 分钟）': 'Generate report (~1–2 minutes)',
 '初筛': 'Screening',
 '删除你的整个空间——弹药库、简历、公司档案、偏好、所有记录——然后像新用户一样重新开通。删除后无法恢复。AI 额度不受影响。': 'Deletes your entire space — Arsenal, '
                                                                   'resumes, company files, preferences, '
                                                                   'every record — and sets you up again as '
                                                                   'a new user. This cannot be undone. Your '
                                                                   'AI credit is not affected.',
 '删除并重新开始': 'Delete and start over',
 '删除本段（先点一次确认）': 'Delete section (click once to confirm)',
 '删除（移入回收站可恢复；自动挖掘不会拉回）': "Delete (moved to trash; auto-discovery won't bring it back)",
 '判题完成': 'Judged',
 '功能': 'Features',
 '动机': 'Motivation',
 '匹配': 'Fit',
 '半自动': 'Manual',
 '危险操作': 'Danger zone',
 '历史报告': 'Past reports',
 '历史（': 'History (',
 '原则：': 'Principle:',
 '原文': 'the text',
 '原文或 JD 链接粘贴到这里（有附件时可空）': 'Paste the text or a JD link here (optional if you attach a file)',
 '去定稿': 'Finalize',
 '去批': 'Review',
 '去设置求职偏好 →': 'Set search preferences →',
 '参与方（、分隔）': 'Participants (comma-separated)',
 '参与方（逗号分隔，可空）': 'Participants (comma-separated, optional)',
 '参谋读全部战况（时间线、JD、尽调档案、评估、弹药库、playbook），出 10 分钟能读完的 brief：⚡ 关键打法置顶 + 局面 + 预判问答（≤5）+ 必问（≤3）；口径与 playbook 只指路不复印。日历自动档（T-24h/T-2h）按事件标题猜轮次。约 30-60 秒。': 'Reads '
                                                                                                                                                     'everything '
                                                                                                                                                     '(timeline, '
                                                                                                                                                     'JD, '
                                                                                                                                                     'research, '
                                                                                                                                                     'assessment, '
                                                                                                                                                     'Arsenal, '
                                                                                                                                                     'playbook) '
                                                                                                                                                     'and '
                                                                                                                                                     'writes '
                                                                                                                                                     'a '
                                                                                                                                                     'brief '
                                                                                                                                                     'you '
                                                                                                                                                     'can '
                                                                                                                                                     'read '
                                                                                                                                                     'in '
                                                                                                                                                     '10 '
                                                                                                                                                     'minutes: '
                                                                                                                                                     '⚡ '
                                                                                                                                                     'key '
                                                                                                                                                     'plays '
                                                                                                                                                     'up '
                                                                                                                                                     'top '
                                                                                                                                                     '+ '
                                                                                                                                                     'situation '
                                                                                                                                                     '+ '
                                                                                                                                                     'likely '
                                                                                                                                                     'questions '
                                                                                                                                                     '(≤5) '
                                                                                                                                                     '+ '
                                                                                                                                                     'must-asks '
                                                                                                                                                     '(≤3). '
                                                                                                                                                     'Calendar '
                                                                                                                                                     'auto-briefs '
                                                                                                                                                     '(T-24h/T-2h) '
                                                                                                                                                     'guess '
                                                                                                                                                     'the '
                                                                                                                                                     'round '
                                                                                                                                                     'from '
                                                                                                                                                     'the '
                                                                                                                                                     'event '
                                                                                                                                                     'title. '
                                                                                                                                                     'About '
                                                                                                                                                     '30–60 '
                                                                                                                                                     'seconds.',
 '参谋部': 'Strategy',
 '参谋部 · joblander': 'Strategy · joblander',
 '发起调研': 'Run research',
 '取消': 'Cancel',
 '取消「在你手上」': 'Unflag "in your court"',
 '取消标记': 'Unflag',
 '叙事': 'Narrative',
 '另有': 'There are also',
 '只影响界面文字；AI 生成的内容暂时仍是中文。': 'Affects interface text only; AI-generated content is still in Chinese for now.',
 '只看活跃': 'Active only',
 '可在设置里关': 'can be turned off in Settings',
 '同一条链接重贴 = 刷新旧快照': ' re-pasting the same link refreshes the snapshot',
 '后台任务——点完随便去哪，右下角看进度，完成自动刷新': 'Runs in the background — feel free to navigate away; progress shows '
                               'bottom-right and the page refreshes when done',
 '后天': 'In 2 days',
 '否决': 'Reject',
 '否决中…': 'Rejecting…',
 '否决所选': 'Reject selected',
 '告诉系统你在找什么': 'Tell us what you are looking for',
 '周': '',
 '周一': 'Mon',
 '周三': 'Wed',
 '周二': 'Tue',
 '周五': 'Fri',
 '周六': 'Sat',
 '周四': 'Thu',
 '周报': 'Weekly',
 '周日': 'Sun',
 '和教练聊：补料 / 提意见 / 问问题（⌘+Enter 发送）——聊归聊；说「出一版」或点 ⚙ 才生成新版': 'Chat with the coach: add facts / give feedback / '
                                                          'ask (⌘+Enter to send) — say "make a version" or '
                                                          'click ⚙ to generate',
 '唯一事实来源': 'single source of truth',
 '喂入 URL（一行一个，可空）': 'Seed URLs (one per line, optional)',
 '喂入材料（可空，按低可信级标注）': 'Seed material (optional, treated as low-confidence)',
 '回到顶部': 'Back to top',
 '在下方「搜索偏好」填目标岗位关键词（比如 <span class="num">Product Manager, Data Engineer</span>）和地点，然后点「立即搜」。': 'Fill in '
                                                                                               'target job '
                                                                                               'titles (e.g. '
                                                                                               '<span '
                                                                                               'class="num">Product '
                                                                                               'Manager, '
                                                                                               'Data '
                                                                                               'Engineer</span>) '
                                                                                               'and '
                                                                                               'locations '
                                                                                               'under '
                                                                                               '"Search '
                                                                                               'preferences" '
                                                                                               'below, then '
                                                                                               'hit "Search '
                                                                                               'now".',
 '在参谋部日报里看完整版': 'See the full daily log',
 '地点': 'Locations',
 '地点（逗号分隔）': 'Locations (comma-separated)',
 '备战': 'Prep',
 '备注': 'Notes',
 '复制原文 →「＋ 贴入」→ 抽取 + 查重 + 评分自动完成': 'Copy the text → "＋ Paste" → extraction, de-dup and scoring happen '
                                   'automatically',
 '复盘': 'Debrief',
 '复盘存档（周报': 'Debrief archive (weekly',
 '复盘已留档': 'Debrief saved',
 '复盘批准即记战况；连续 2 miss 自动升 needs_work': 'Approved debriefs record outcomes; 2 misses in a row escalate to '
                                      'needs_work',
 '失败': 'Failed',
 '失败：': 'Failed: ',
 '字段建议': 'Field suggestion',
 '存入弹药库': 'Save',
 '完成': 'Done',
 '完成（{n} 个源失败）': 'Done ({n} sources failed)',
 '完成，刷新中…': 'Done, refreshing…',
 '完整评审报告': 'Full review report',
 '定制 v': 'Tailored v',
 '定制动作：': 'Tailoring changes:',
 '定制简历': 'Tailored resume',
 '定制简历 · {co}': 'Tailored resume · {co}',
 '定稿入日报': 'Finalize to daily log',
 '实际\u3000': 'Actual ',
 '实际发给对方的是哪版——母版直发或定制简历的具体 v 号（对应版本链，一查便知）': 'Which version you actually sent — a master resume or a '
                                             'specific tailored version',
 '家': 'companies',
 '对外报价的锚点。Offer 对比按它算差距，屏幕上只显示百分比。': 'Your quoting anchor. Offer comparison measures gaps against it and '
                                     'only shows percentages on screen.',
 '对比矩阵（按折价 TC 排序）': 'Comparison (sorted by discounted TC)',
 '尽调 · {co}': 'Research · {co}',
 '尽调员多轮检索出带来源简介；有料可喂入当种子，留空全自动': 'Multi-round research into a sourced company profile; seed it with material '
                                 'or leave empty for fully automatic',
 '尽调员多轮检索循环：读材料 → 判五项覆盖（动因/面试/技术栈/薪酬/稳定性）→ 为缺口出新查询，直到覆盖或确认死角，出综合简介（每个断言带编号来源）落时间线，末尾附逐轮轨迹；结构化证据进档案，「评估匹配」自动引用。约 2-3 分钟。': 'Multi-round '
                                                                                                                          'research '
                                                                                                                          'loop: '
                                                                                                                          'read '
                                                                                                                          'sources '
                                                                                                                          '→ '
                                                                                                                          'check '
                                                                                                                          'coverage '
                                                                                                                          'of '
                                                                                                                          'five '
                                                                                                                          'areas '
                                                                                                                          '(motivation '
                                                                                                                          '/ '
                                                                                                                          'interviews '
                                                                                                                          '/ '
                                                                                                                          'tech '
                                                                                                                          'stack '
                                                                                                                          '/ '
                                                                                                                          'pay '
                                                                                                                          '/ '
                                                                                                                          'stability) '
                                                                                                                          '→ '
                                                                                                                          'search '
                                                                                                                          'for '
                                                                                                                          'gaps '
                                                                                                                          'until '
                                                                                                                          'covered '
                                                                                                                          'or '
                                                                                                                          'confirmed '
                                                                                                                          'blind '
                                                                                                                          'spots '
                                                                                                                          '→ '
                                                                                                                          'a '
                                                                                                                          'sourced '
                                                                                                                          'profile '
                                                                                                                          '(every '
                                                                                                                          'claim '
                                                                                                                          'numbered) '
                                                                                                                          'on '
                                                                                                                          'the '
                                                                                                                          'timeline, '
                                                                                                                          'with '
                                                                                                                          'the '
                                                                                                                          'round-by-round '
                                                                                                                          'trail; '
                                                                                                                          'structured '
                                                                                                                          'evidence '
                                                                                                                          'is '
                                                                                                                          'saved '
                                                                                                                          'and '
                                                                                                                          'used '
                                                                                                                          'by '
                                                                                                                          'Assess '
                                                                                                                          'fit. '
                                                                                                                          'About '
                                                                                                                          '2–3 '
                                                                                                                          'minutes.',
 '尽调报告：公司综合简介': 'Deep Research: company profile',
 '岗位': 'Role',
 '岗位 ✎': 'Role ✎',
 '岗位亮点 ✎': 'Role highlights ✎',
 '差 1 琥珀': 'gap 1 amber',
 '差 ≥2 红': 'gap ≥2 red',
 '已保存': 'Saved',
 '已保存（旧版在 jd/.trash 可恢复）': 'Saved (old version kept in trash)',
 '已保存，重新计算': 'Saved, recalculating',
 '已入库': 'Saved',
 '已入待入池': 'Added to the review queue',
 '已入档': 'Saved',
 '已入池': 'Added to pipeline',
 '已关闭': 'Disabled',
 '已关闭：': 'Closed: ',
 '已写回，条目已入时间线': 'Saved; entry added to the timeline',
 '已写我的复盘': 'Has my debrief',
 '已删除': 'Deleted',
 '已删除——公司档案保留': 'Deleted — company file kept',
 '已删除（附件保留）': 'Deleted (attachments kept)',
 '已取消标记': 'Unflagged',
 '已否决': 'Rejected',
 '已否决 {n} 条': 'Rejected {n}',
 '已存': 'Saved',
 '已定稿 · ': 'Finalized · ',
 '已定稿入日报': 'Saved to daily log',
 '已开启': 'Enabled',
 '已投': 'Applied',
 '已替换': 'Replaced',
 '已标记：在你手上': 'Flagged: in your court',
 '已校准——重估也不会被推翻': "Calibrated — re-assessment won't override it",
 '已根据你的简历猜了一组目标岗位和城市，并替你跑了第一轮搜索。去「新机会」核对一下——改准了，之后每晚的搜索和打分都会更准。': 'We guessed target roles and cities from '
                                                                  'your resume and ran a first search for '
                                                                  'you. Check them on New Leads — the more '
                                                                  'accurate they are, the better every '
                                                                  'nightly search and score will be.',
 '已清空（旧版本已归档）': 'Cleared (old versions archived)',
 '已移入回收站（jd/.trash 可恢复；自动挖掘不会拉回）': "Moved to trash (recoverable; auto-discovery won't bring it back)",
 '已移到「': 'Moved to "',
 '已移除——文件保留在未绑附件区': 'Detached — file kept under unlinked files',
 '已记录': 'Recorded',
 '已跳过，随时回这里补': 'Skipped — come back here anytime',
 '币种': 'Currency',
 '带 ✎ 的点值即改': 'Click any ✎ value to edit',
 '建议补充的信息（弹药库缺，对话里丢给教练即可）：': 'Suggested info to add (missing from your Arsenal — just tell the coach):',
 '开始设置': 'Getting started',
 '引擎在线（本机）': 'Engine online (local)',
 '弹药库': 'Arsenal',
 '弹药库 · joblander': 'Arsenal · joblander',
 '弹药库 × 该司 JD → 定制 HTML/PDF，产出过红线守卫；评审=招聘方盲评+教练分拣': 'Arsenal × this JD → tailored HTML/PDF, checked by the '
                                                    'red-line guard; review = blind recruiter review + coach '
                                                    'triage',
 '弹药库已更新': 'Arsenal updated',
 '弹药库已生成。它是之后所有简历和 brief 的<b>唯一事实来源</b>——去逐段核对，补上简历里装不下的细节，写得越实，定制出来越好。': 'Your Arsenal is ready. It is the '
                                                                          '<b>single source of truth</b> for '
                                                                          'every resume and brief from now '
                                                                          'on — review it section by section '
                                                                          'and add the details your resume '
                                                                          'had no room for. The richer it '
                                                                          'is, the better the tailoring.',
 '弹药库已经有内容了——去弹药库页直接编辑': 'Your Arsenal already has content — edit it on the Arsenal page',
 '弹药库已经有内容了——去弹药库页直接编辑，向导不覆盖': 'Your Arsenal already has content — edit it on the Arsenal page; setup will '
                               'not overwrite it',
 '弹药库正在生成中——稍等一分钟，不用重复点': 'Your Arsenal is being built — give it a minute, no need to click again',
 '归档计划：': 'Filing plan:',
 '当前': 'Current',
 '当前阶段 ✎': 'Stage ✎',
 '待你批（': 'Awaiting your approval (',
 '待入池（{n} 岗 · 按公司聚合，已在库公司不出现在这里）': 'To review ({n} roles · grouped by company; companies already in your '
                                   'pipeline are hidden)',
 '待批': 'Pending',
 '待批提案或到期 follow-up': 'Pending proposals or follow-ups due',
 '待批提案或到期 follow-up——点卡片进档案页处理': 'Pending proposals or follow-ups due — click to open the company page',
 '待批提案（长在各自属地）': 'Proposals awaiting approval',
 '待申请': 'To apply',
 '我的复盘': 'My debrief',
 '我的复盘（AI 的归 AI，你的判断单独留档；清空即删）': 'My debrief (kept separately from AI content; clear it to delete)',
 '或 bonus %': 'or bonus %',
 '或传文件（PDF / txt / md）': 'Or upload a file (PDF / txt / md)',
 '或选文件': 'Or choose files',
 '战况（': 'Record (',
 '战线・公司档案・提案・日记 = 实时': 'pipeline, files, proposals, diary = live',
 '所选全部否决——只记账，可反悔': 'Reject all selected — logged, reversible',
 '手上是什么形态就给什么：': 'Give whatever you have:',
 '手头有料就喂进来当种子（种子打底，缺口照常补搜；登录态站点如 LinkedIn 打不开——复制正文贴材料框）；两栏都留空 = 零输入全自动检索。': 'Seed it with anything you have '
                                                                             '(gaps are still searched; for '
                                                                             'login-only sites like '
                                                                             'LinkedIn, paste the text); '
                                                                             'leave both empty for fully '
                                                                             'automatic research.',
 '手记已存': 'Notes saved',
 '手记已存进日报': 'Notes saved to daily log',
 '手调': 'adjusted',
 '打印 / PDF': 'Print / PDF',
 '打开弹药库核对 →': 'Review your Arsenal →',
 '打开档案': 'Open file',
 '打开链接': 'Open link',
 '扫 MyCareersFuture': 'Scan MyCareersFuture',
 '扫全部 JD + 复盘证据 + 初筛差距，重出能力画像（LLM，约 1 分钟）': 'Re-builds your capability profile from all JDs, debrief '
                                            'evidence and screening gaps (AI, ~1 minute)',
 '扫描版 PDF 读不出文字；用 Word 或能选中文字的 PDF。': "Scanned PDFs can't be read — use Word or a PDF with selectable text.",
 '扫描邮箱': 'Scan inbox',
 '批准执行（可先改字段）': 'Approve (edit fields first if needed)',
 '技术': 'Technical',
 '技术轮': 'Technical',
 '投出的版本': 'Version sent',
 '投递': 'Applied',
 '投递日 ✎': 'Applied on ✎',
 '折价档': 'Discount tier',
 '折价档名来自私有 policy（如 liquid/heavy）': 'Tier names come from your policy config (e.g. light/heavy)',
 '报价按面值、比较按折价': 'quote at face value, compare at discounted value',
 '抽取 → 待入池': 'Extract → review queue',
 '拆分结果不是合法 JSON——重试一次': 'The AI returned an unreadable result — please try again',
 '拖拽排序': 'Drag to reorder',
 '招聘方修改建议：': 'Recruiter suggestions:',
 '招聘方盲评（HR 初筛 + HM 细读）+ 教练分拣，按需手动跑，不占生成时间': 'Blind recruiter review (HR screen + hiring-manager read) + '
                                            'coach triage; run on demand',
 '招聘方评估 · {co}': 'Recruiter review · {co}',
 '指挥中心': 'Command Center',
 '按 JD + 本人材料 + 薪酬信号出匹配快照与雷达（LLM，约 30-45 秒）': 'Fit snapshot and radar from the JD, your materials and pay '
                                              'signals (AI, ~30–45 s)',
 '按 LinkedIn 人脉地图选内推人 + 触达草稿（你来发）落时间线': 'Pick a referrer from your LinkedIn network map + outreach draft '
                                        '(you send it), added to the timeline',
 '按日分组 · 点标题展开 ｜': 'Grouped by day · click a title to expand |',
 '按求职偏好每晚搜一次 LinkedIn 公开职位（免登录接口），和 MCF 一起打分入池。接口随时可能被 LinkedIn 调整或限流。': "Searches LinkedIn's public job "
                                                                         'listings nightly using your '
                                                                         'preferences (no login), scored '
                                                                         'alongside MCF. LinkedIn may change '
                                                                         'or rate-limit this at any time.',
 '按编辑框当前值写字段 + 条目入下方时间线 + 回写 Playbook 战况': 'Write the fields as edited + add the entry to the timeline + '
                                           'update the Playbook',
 '按详情创建 Google Calendar 事件——这一步就是逐次确认': 'Create the Google Calendar event — this click is your confirmation',
 '排期参谋 · {co}': 'Scheduling · {co}',
 '排期参谋（W6）': 'Scheduling assistant',
 '排期参谋：候选时段对照与回复草稿': 'Scheduling: proposed slots and reply draft',
 '排除词': 'Exclude',
 '排除词（命中直接丢弃，不进待入池）': 'Exclude words (matching titles are dropped)',
 '推进': 'Follow up',
 '提案就绪——就在本页「待你批」': 'Proposal ready — see "Awaiting your approval" on this page',
 '搜新机会': 'Search new leads',
 '搜索偏好（喂给评分器和搜索源）': 'Search preferences (used for search and scoring)',
 '支持 PDF / Word / Markdown / 纯文本简历': 'Supported: PDF / Word / Markdown / plain-text resumes',
 '收到。': 'Got it.',
 '改': 'Edit',
 '改动即刻喂给评分器与搜索源；存私有 workspace，不进代码库。': 'Changes take effect immediately and are stored only in your private '
                                       'workspace.',
 '教练': 'Coach',
 '数据源：': 'Sources:',
 '文件': 'files',
 '文化': 'Culture',
 '新机会': 'New Leads',
 '新条目「': 'New entry "',
 '无': 'none',
 '无 High 行': 'No high-priority rows',
 '无变更': 'No changes',
 '无逾期 ✅': 'nothing overdue ✅',
 '无面试场次 ✅': 'No interviews ✅',
 '日历事件已创建': 'Calendar event created',
 '日历同步': 'Calendar sync',
 '日报': 'Daily',
 '日期': 'Date',
 '日记草稿就绪——在下方改两句，定稿进参谋部日报': 'Diary draft ready — tweak it below and finalize it into your daily log',
 '时长（分）': 'Duration (min)',
 '时间': 'Time',
 '时间线': 'Timeline',
 '明天': 'Tomorrow',
 '暂无待决策线索 ✅ 每晚自动搜，有新的会出现在这里。等不及就点上面的「立即搜」。': 'Nothing to review ✅ We search every night and new leads will '
                                             'show up here. Can’t wait? Hit "Search now" above.',
 '更多动作': 'More actions',
 '替换（选新文件顶掉这份）': 'Replace (pick a new file)',
 '月 base': 'Monthly base',
 '期权面值/年': 'Equity face/yr',
 '未分组': 'Ungrouped',
 '未归类': 'Uncategorized',
 '未绑附件': 'Unlinked files',
 '未记录': 'Not recorded',
 '本场特别注意（可空）': 'Anything special about this round (optional)',
 '本版意见：': 'Feedback for this version:',
 '条事实 · 评估匹配自动引用）': ' facts · used automatically by Assess fit)',
 '条初筛差距 + 履历 ｜': ' screening gaps + background |',
 '条：既往版本与对话）': ' items: past versions and chat)',
 '来源': 'Source',
 '来源：': 'Sources:',
 '来源：tracker↔日历每周对账（{n}）——补上时间就能建入 Google 日历，或否决': 'Source: weekly pipeline↔calendar check ({n}) — add the '
                                                   'time to create the event, or reject',
 '标准版': 'Standard',
 '标准版（母版）': 'Standard (master)',
 '标记「在你手上」——球在你这边，突出显示': 'Flag "in your court" — highlighted',
 '标题': 'Title',
 '标题（事件/人名）': 'Title (event / person)',
 '校准当前能力：': 'Calibrate current level:',
 '模式与问题库': 'Patterns & question bank',
 '正在重置——马上带你重新开始': 'Resetting — taking you back to the start',
 '段内部使用规则不在此展示，生成简历 / brief / 策略时照常生效。': 'internal rule sections not shown here; they still apply when '
                                         'generating resumes, briefs and strategy.',
 '段标题': 'Section title',
 '段标题（如：某公司 —— 岗位（起止时间））': 'Section title (e.g. Company — Role (dates))',
 '每 30 分钟自动一轮，分类闸过滤非机会': 'Every 30 minutes; non-opportunities are filtered out',
 '每周日 20:00 自动生成。': 'Generated every Sunday at 20:00.',
 '每天 08:15 落档。': 'Filed daily at 08:15.',
 '每晚 02:30 按你的偏好搜 {src} 的新岗位 → 去重 → 对照弹药库打匹配分、初筛硬性要求 → 在这里等你决定入不入池。': 'Every night at 02:30 we search {src} '
                                                                      'for new roles matching your '
                                                                      'preferences → de-duplicate → score '
                                                                      'fit against your Arsenal and screen '
                                                                      'hard requirements → they wait here '
                                                                      'for your decision.',
 '每晚 02:30 按偏好关键词抓新岗': 'Searched nightly at 02:30 using your keywords',
 '每晚 02:30 进': 'nightly 02:30 into',
 '每晚按关键词 × 首选地点搜近 48h 公开职位': 'Public listings from the last 48h, searched nightly by keyword × preferred '
                             'location',
 '求职意向': 'Looking for',
 '求职意向（一句话，评分器主要看这个）': 'What you are looking for (one sentence — the scorer relies on this most)',
 '没有 offer 时也可以先拿「假想 offer」演习谈判空间；数据存私有 workspace（15-offers/）。': 'No offers yet? Try hypothetical ones to '
                                                                 'rehearse your negotiation room; data stays '
                                                                 'in your private workspace.',
 '没能从简历里拆出任何条目——换一份文字版简历（不是扫描图片）再试': "Couldn't extract any entries — try a text-based resume (not a scanned "
                                     'image)',
 '没能从简历里认出姓名和联系方式——定制简历的抬头需要它，请在 workspace 的 03-materials/profile.json 补上。': "Couldn't find your name and "
                                                                             'contact details in the resume '
                                                                             '— tailored resumes need them '
                                                                             'for the header. Add them in '
                                                                             '03-materials/profile.json.',
 '活跃': 'Active',
 '活跃战线 {a}/{b} 行': '{a}/{b} active',
 '清空对话与版本从头开始：旧版本与对话归档到 resume/archive-*（不物理删除）；「投出的版本」记录保留': 'Start over: old versions and chat are '
                                                              'archived (not deleted); the "version sent" '
                                                              'record is kept',
 '清空草稿，回到起始模板': 'Clear draft and reset to the starter code',
 '清除': 'Clear',
 '清除链接（可重填）': 'Clear link (you can re-add it)',
 '渠道': 'Channels',
 '点击原位编辑': 'Click to edit in place',
 '点击原位编辑：一行一条，失焦保存，Esc 取消': 'Click to edit: one per line, saves on blur, Esc cancels',
 '点改优先级': 'Click to change priority',
 '点改公司名（本地档案/附件/简历版本会跟着搬家）': 'Click to rename (files, attachments and resume versions move with it)',
 '版': '',
 '状态 ⇅': 'Status ⇅',
 '现在生成': 'generate it now',
 '现金/年': 'Cash/yr',
 '球在你这边（自动待办算不出来的），作战室会突出显示': "Ball's in your court (things auto-todos can't detect); highlighted in War "
                              'Room',
 '生成': 'Generate',
 '生成 brief': 'Generate brief',
 '生成 brief · {co}': 'Brief · {co}',
 '生成 brief（W7/W5）': 'Generate brief',
 '生成定制简历': 'Generate tailored resume',
 '生成提案（不直接写入）': 'Create proposal (nothing written yet)',
 '申请 / 初筛': 'Applied / screening',
 '画像已重估': 'Profile re-assessed',
 '的 JD ｜ 自身侧：': "' JDs | Your side:",
 '目标岗位、城市、关键词和排除项——每晚的搜索和打分按这个来。': 'Target roles, cities, keywords and exclusions — nightly search and '
                                   'scoring follow these.',
 '目标岗位关键词（逗号分隔，MCF / LinkedIn 按这个搜）': 'Target job titles (comma-separated — used to search MCF / LinkedIn)',
 '目标年度总包要填一个正数': 'Target annual total comp must be a positive number',
 '目标年度总包（base + bonus + equity）': 'Target annual total comp (base + bonus + equity)',
 '目标薪资与红线': 'Target pay and red lines',
 '直接在下面改，定稿即入 {d}.md 的「今日日记」段': 'Edit below; finalizing saves it to the diary section of {d}.md',
 '看板': 'Board',
 '看板拖卡片换阶段；表格点单元格原位改——两种都直接写回。': 'Drag cards on the board to change stage; click a table cell to edit in '
                                 'place — both save immediately.',
 '看首轮结果、核对偏好 →': 'See first results and check preferences →',
 '硬检查': 'Hard checks',
 '确认删除？': 'Confirm delete?',
 '确认建事件': 'Create event',
 '确认清空？（旧版本会归档）': 'Confirm start over? (old versions are archived)',
 '笔记': 'Note',
 '笔试': 'Assessment',
 '等你批（改/批都在档案页）': ' awaiting your approval (edit/approve on the company page)',
 '策略已保存——点「重估能力画像」生效': 'Scope saved — click "Re-assess profile" to apply',
 '简历、面试、LinkedIn 的唯一取材地——能讲的、能打的案例和经历，按公司/项目分段，写任何对外材料都从这里取。': 'The single source for resumes, interviews '
                                                               'and LinkedIn — your stories and '
                                                               'achievements, by company/project. Everything '
                                                               'you send out draws from here.',
 '简历文字太少——可能是扫描版 PDF，换一份能选中文字的版本': 'Too little text — it may be a scanned PDF; use a version with selectable '
                                   'text',
 '简历母版': 'Master resumes',
 '算法题练习，可在线运行代码——偏软件工程岗位。开启后侧栏出现入口。': 'Coding interview practice with in-browser code execution — mainly for '
                                      'software roles. Adds an entry to the sidebar.',
 '类型': 'Type',
 '系统': 'System',
 '系统产出 ·': 'generated ·',
 '系统会把简历拆成按公司/项目分段的「战绩弹药库」：只搬运简历里写了的事实，不补写、不美化。大约需要一分钟。': 'Your resume is split into an "Arsenal" of '
                                                          'achievements, grouped by company/project. Only '
                                                          'facts that are in your resume are carried over — '
                                                          'nothing added, nothing embellished. Takes about a '
                                                          'minute.',
 '素材=各公司档案今天的战线事件；数据同步、评估重算这类系统动作不入日记。定稿落参谋部日报。': "Built from today's events in your company files (system "
                                                  'actions are left out). Finalized entries go to your daily '
                                                  'log.',
 '素材段都是内部规则——先「＋ 新增素材段」放第一条战绩进来。': 'Only rule sections so far — add your first achievements with "＋ New '
                                   'section".',
 '红线词（可空，一行一个）': 'Red-line words (optional, one per line)',
 '线索': 'Leads',
 '练兵场': 'Practice',
 '练兵场 · joblander': 'Practice · joblander',
 '练兵场未开启（设置 → 功能）': 'Practice is off (Settings → Features)',
 '细节': 'Details',
 '结构与样式的基底；公司定制版长在各公司页的教练对话里，此处不重复陈列': 'The base for structure and style; tailored versions live in each '
                                       "company page's coach chat",
 '给这条事件挂附件（可多选）': 'Attach files to this event (multiple allowed)',
 '编辑': 'Edit',
 '编辑（旧版自动存回收站可恢复）': 'Edit (the old version is kept in the trash)',
 '缺口': 'gap',
 '缺失': 'missing',
 '聊归聊、版归版：补料/提意见先跟教练聊（意见累积，下次整份重新生成），说「出一版」或点 ⚙ 才生成 · 事实定点入弹药库 · 版本只增不覆盖': 'Chat is separate from versions: '
                                                                           'add facts or feedback in chat '
                                                                           '(it accumulates for the next '
                                                                           'full regeneration); say "make a '
                                                                           'version" or click ⚙ to generate '
                                                                           '· facts go into the Arsenal · '
                                                                           'versions are never overwritten',
 '联系人 ✎': 'Contact ✎',
 '能力画像': 'Capability profile',
 '能力画像（市场要求 vs 当前能力）｜ 模式与问题库 ｜ 复盘存档。画像每周日随周报自动重估。': 'Capability profile (market needs vs. your current '
                                                    'level) | patterns & question bank | debrief archive. '
                                                    'The profile is re-assessed every Sunday with the weekly '
                                                    'report.',
 '自动': 'Auto',
 '自动搜索已关（可在设置里开）。深链按你的关键词拼好近 24h 搜索——看到好的用「＋ 贴入」丢回来：': 'Automatic search is off (turn it on in Settings). '
                                                       'These links open a last-24h search for your keywords '
                                                       '— paste back anything good with "＋ Paste":',
 '自定义 ': 'Custom ',
 '自定义点名': 'Custom pick',
 '自定义（从作战室点名）': 'Custom (pick from War Room)',
 '草稿 21:30 自动生成，也可以': 'A draft is generated at 21:30, or you can',
 '草稿已生成': 'Draft generated',
 '草稿由你自己发出。': 'You send the draft yourself.',
 '薪酬': 'Compensation',
 '薪酬匹配': 'Pay fit',
 '薪酬调研': 'Compensation research',
 '薪酬调研（W4）': 'Compensation research',
 '行为': 'Behavioral',
 '补充 URL（一行一个，可空）': 'Extra URLs (one per line, optional)',
 '补充偏好': 'Other preferences',
 '补充偏好（自由文本：公司类型、避雷、加分项）': 'Other preferences (free text: company types, deal-breakers, nice-to-haves)',
 '补充材料': 'supporting material',
 '补时间建入日历': 'Add the time to create a calendar event',
 '表格': 'Table',
 '记录': 'Note',
 '记录 · 字段建议': 'Note · field suggestions',
 '设优先级 ✎': 'Set priority ✎',
 '设置': 'Settings',
 '评估': 'Assessment',
 '评估中': 'Evaluating',
 '评估于': 'Assessed',
 '评估完成': 'Assessment done',
 '评分依据 · 弹药库': 'Scored against · Arsenal',
 '评分器实际吃到 {n} 字符（上限 12,000，超出截断）。': 'The scorer reads {n} characters (capped at 12,000).',
 '请输入 RESET 确认': 'Type RESET to confirm',
 '读不出简历文字——可能是扫描版，换一份能选中文字的版本': "Couldn't read any text — it may be a scanned file; use a version with "
                                'selectable text',
 '调研档案（': 'Research file (',
 '谈判提醒：重折价期权的公司谈判重心压现金；多 offer 对齐时间窗制造竞争；对外口径以 brief 的口径卡为准。': 'Negotiation tips: with heavily discounted '
                                                               'equity, push on cash; align offer timelines '
                                                               "to create competition; use your brief's "
                                                               'talking points externally.',
 '谈判轮': 'Negotiation',
 '贴 WhatsApp / InMail / 邮件 / JD 原文，或直接贴 JD 链接（LinkedIn / MCF / 官网，自动解析页面），也可以只传一个 JD 附件——抽取、查重后进审批，批准才建行。': 'Paste '
                                                                                                            'a '
                                                                                                            'WhatsApp '
                                                                                                            '/ '
                                                                                                            'InMail '
                                                                                                            '/ '
                                                                                                            'email '
                                                                                                            '/ '
                                                                                                            'JD, '
                                                                                                            'or '
                                                                                                            'just '
                                                                                                            'a '
                                                                                                            'JD '
                                                                                                            'link '
                                                                                                            '(LinkedIn '
                                                                                                            '/ '
                                                                                                            'MCF '
                                                                                                            '/ '
                                                                                                            'company '
                                                                                                            'site '
                                                                                                            '— '
                                                                                                            'parsed '
                                                                                                            'automatically), '
                                                                                                            'or '
                                                                                                            'upload '
                                                                                                            'a '
                                                                                                            'JD '
                                                                                                            'file. '
                                                                                                            'It '
                                                                                                            'is '
                                                                                                            'extracted '
                                                                                                            'and '
                                                                                                            'de-duplicated, '
                                                                                                            'then '
                                                                                                            'waits '
                                                                                                            'for '
                                                                                                            'your '
                                                                                                            'approval '
                                                                                                            'before '
                                                                                                            'anything '
                                                                                                            'is '
                                                                                                            'created.',
 '贴入': 'Paste',
 '贴入含时间的邀约：抽取候选时段 → 对照日历跑排期规则 → 推荐 + 回复草稿（你来发）': 'Paste an invite with times: extract slots → check against '
                                                 'your calendar rules → recommendation + reply draft (you '
                                                 'send it)',
 '贴入对方的时间邀约（邮件全文即可）。抽取候选时段 → 对照未来 14 天日历跑规则（同日硬面 ≤2 · 缓冲 ≥30min · 技术轮前保护 ≥4h）→ 时段对照 + 回复草稿落入下方时间线。': 'Paste '
                                                                                                     'their '
                                                                                                     'scheduling '
                                                                                                     'invite '
                                                                                                     '(the '
                                                                                                     'whole '
                                                                                                     'email '
                                                                                                     'is '
                                                                                                     'fine). '
                                                                                                     'Slots '
                                                                                                     'are '
                                                                                                     'extracted '
                                                                                                     'and '
                                                                                                     'checked '
                                                                                                     'against '
                                                                                                     'your '
                                                                                                     'next '
                                                                                                     '14 '
                                                                                                     'days '
                                                                                                     '(≤2 '
                                                                                                     'interviews '
                                                                                                     'per '
                                                                                                     'day · '
                                                                                                     '≥30 '
                                                                                                     'min '
                                                                                                     'buffer '
                                                                                                     '· ≥4 h '
                                                                                                     'before '
                                                                                                     'technical '
                                                                                                     'rounds) '
                                                                                                     '→ slot '
                                                                                                     'comparison '
                                                                                                     '+ '
                                                                                                     'reply '
                                                                                                     'draft '
                                                                                                     'on the '
                                                                                                     'timeline.',
 '贴入材料（可空）': 'Pasted material (optional)',
 '贴转写全文或传 PDF——Scribe 出「字段 + 正文 + Playbook 战况」提案，到审批队列改/批后才入档写回。': 'Paste a transcript or upload a PDF — '
                                                                   'Scribe proposes field updates, notes and '
                                                                   'Playbook records; nothing is saved until '
                                                                   'you approve.',
 '资产（': 'Assets (',
 '起草今日日记': "Draft today's diary",
 '跟进更新': 'Follow-up update',
 '转写': 'Transcript',
 '转写 → 录入': 'Transcript → log',
 '转写 → 录入提案': 'Transcript → proposal',
 '转写全文（可空，若传文件）': 'Transcript (optional if you upload a file)',
 '轮次': 'Round',
 '输入 RESET 确认': 'Type RESET to confirm',
 '输入框有内容=发给教练（教练判断：明确说出版才生成）；空着点=直接出新版（吃已攒的全部意见，一次生成，不自动改稿）。想看招聘方视角反馈，出版后点「🔍 评审这版」；版本只增不覆盖': 'With text: '
                                                                                             'sends to the '
                                                                                             'coach (it only '
                                                                                             'generates if '
                                                                                             'you clearly '
                                                                                             'ask). Empty: '
                                                                                             'generates a '
                                                                                             'new version '
                                                                                             'using all '
                                                                                             'accumulated '
                                                                                             'feedback. For '
                                                                                             'recruiter-eye '
                                                                                             'feedback, '
                                                                                             'click "🔍 '
                                                                                             'Review this '
                                                                                             'version" '
                                                                                             'afterwards; '
                                                                                             'versions are '
                                                                                             'never '
                                                                                             'overwritten',
 '达标': 'met',
 '还没有素材库文件——「＋ 新增素材段」写第一条即建。': 'No Arsenal yet — "＋ New section" creates it.',
 '还没有能力画像——点右上「重估能力画像」，从你的 JD 库与复盘里挖一份出来（市场侧默认取 High 优先级机会的 JD，生成后可在本区改为自定义公司清单）。': 'No capability profile '
                                                                                    'yet — click "Re-assess '
                                                                                    'profile" (top right) to '
                                                                                    'build one from your JDs '
                                                                                    'and debriefs (market '
                                                                                    'side defaults to '
                                                                                    'high-priority leads; '
                                                                                    'you can switch to a '
                                                                                    'custom list '
                                                                                    'afterwards).',
 '还没有记录。「＋ 记录」写第一条，或「转写 → 录入」让系统替你写。': 'Nothing logged yet. Use "＋ Note" to write the first entry, or '
                                       '"Transcript → log" to let the system write it.',
 '还没评估过。传 JD 后点顶栏 ⋯ →「评估匹配」，出 JD 匹配度 + 薪酬匹配度 + 匹配雷达。': 'Not assessed yet. Add a JD, then ⋯ → "Assess fit" '
                                                       'for JD fit, pay fit and a fit radar.',
 '还没跑过。左边发起第一份——按你的求职意向抓 MCF 实时薪资，出带日期的结构化报告。': 'None yet. Run your first one on the left — it pulls live '
                                                'MCF pay for your target roles into a dated report.',
 '进入待入池的时间': 'When it entered the queue',
 '进入指挥中心 →': 'Go to Command Center →',
 '进行中——右下角看进度': 'in progress — see bottom-right',
 '退出登录': 'Sign out',
 '选低匹配': 'Select low-fit',
 '通用（不指定轮次）': 'General (no specific round)',
 '通话': 'Call',
 '逾期': 'Overdue',
 '逾期 follow-up': 'Overdue follow-ups',
 '邀约原文': 'Invite text',
 '邮件': 'Email',
 '重估能力画像': 'Re-assess capability profile',
 '重置': 'Reset',
 '重置失败：': 'Reset failed: ',
 '重置账户，从头开始': 'Reset your account and start over',
 '重跑「评估匹配」即出 JD 定制雷达（轴从该 JD 提炼，不套通用模板）。': 'Re-run "Assess fit" for a JD-specific radar (axes are drawn from '
                                          'this JD).',
 '链接': 'a link',
 '链接、原文、文件总得给一样': 'Give a link, text or a file',
 '链接、原文、文件都行——给了 JD，「评估匹配」才有的吃。': 'A link, pasted text or a file all work — "Assess fit" needs a JD to work '
                                  'with.',
 '附件': 'Attachments',
 '附件上传失败': 'Attachment upload failed',
 '附件已入档': 'Attachment saved',
 '附件（可空，可多选）': 'Attachments (optional, multiple allowed)',
 '附件：{name}': 'Attachment: {name}',
 '随机一道 LeetCode Medium。先想清楚「问题 → 数据结构与算法」的映射再动手；卡住了再开提示。一期只支持 Python3。': 'A random LeetCode Medium. Map the '
                                                                         'problem to a data structure and '
                                                                         'algorithm before coding; open '
                                                                         'hints only when stuck. Python 3 '
                                                                         'only for now.',
 '集团冲突：': 'Group conflict: ',
 '需': 'needs',
 '面后录入': 'Post-interview notes',
 '面后录入 / 跟进更新——批准才写入档案；字段框可先改': 'Post-interview notes / follow-up updates — nothing is written until you '
                                'approve; fields are editable first',
 '面试': 'Interview',
 '面试中': 'Interviewing',
 '顺序已保存': 'Order saved',
 '顺手生成了字段建议——本页「待你批」区等你': 'Field suggestions were generated too — see "Awaiting your approval" on this page',
 '预览': 'Preview',
 '首次使用需配一个免费 search key': 'A free search key is needed the first time',
 '首次搜新机会': 'First search for new leads',
 '首轮搜索已经按它跑过了。核对一下关键词和地点——改准了，之后每晚的搜索和打分都会更准。': 'A first search has already run with them. Check the '
                                                'keywords and locations — the more accurate they are, the '
                                                'better every nightly search and score.',
 '默认用「新机会」页侦察偏好里的关键词搜 MCF；可临时覆盖。levels.fyi/Glassdoor 等登录站点把内容贴进材料框。锚点对照只显示相对百分比，报告可安全分享。': 'Uses the '
                                                                                           'keywords from '
                                                                                           'your New Leads '
                                                                                           'preferences to '
                                                                                           'search MCF by '
                                                                                           'default; you can '
                                                                                           'override them. '
                                                                                           'Paste content '
                                                                                           'from login-only '
                                                                                           'sites like '
                                                                                           'levels.fyi / '
                                                                                           'Glassdoor. '
                                                                                           'Anchor '
                                                                                           'comparisons show '
                                                                                           'percentages '
                                                                                           'only, so reports '
                                                                                           'are safe to '
                                                                                           'share.',
 '（LLM 原判': ' (AI rated',
 '（PDF/文本，可多选）。一律存进本地 JD 档案，评估与备战自动引用（多份并存都算数）；贴链接时「JD 链接」为空会顺手填上，': ' (PDF/text, multiple allowed). '
                                                                     'Everything is saved to the JD file and '
                                                                     'used automatically by assessment and '
                                                                     'prep; pasting a link also fills an '
                                                                     'empty "JD link";',
 '（tavily.com 注册约 1 分钟，config 的 search 段填入——没配会明确报错不瞎跑）。': ' (sign up at tavily.com, ~1 minute, and add it '
                                                           'to the search section of config).',
 '（含 LinkedIn Job Alert 邮件）': ' (incl. LinkedIn Job Alert emails)',
 '（官网 / MCF 自动抓正文；LinkedIn 常要登录，抓不到会明说——那就贴原文）、': ' (company sites / MCF are fetched automatically; LinkedIn '
                                                  'often needs login — paste the text if it fails), ',
 '（批准后自动回写）': ' (written back on approval)',
 '（日历缓存等 daemon 刷新，最长 30 分钟）': ' (calendar cache refreshes within 30 min)',
 '（旧记录）': ' (old record)',
 '（未填，点下面「下一步」补一句）': '(empty — add one under "Next step" below)',
 '（清空）': '(cleared)',
 '（直接粘贴），或': ' (paste it), or',
 '（系统内阅读；PDF 原样打开）': ' (read in-app; PDFs open as-is)',
 '（维度名变了，重新校准一次即可）': ' (dimension names changed — just recalibrate)',
 '（要采纳就在下面改）': ' (change it below to accept)',
 '（重发即可）': ' (just resend)',
 '）——按日期索引': ') — by date',
 '）——这是看板上标橙色的原因，下一步：': ") — that's why it's orange on the board. Next step:",
 '＋ 写我的复盘': '＋ Write my debrief',
 '＋ 加一个 offer': '＋ Add an offer',
 '＋ 新增素材段': '＋ New section',
 '＋ 新机会': '＋ New lead',
 '＋ 添加 JD': '＋ Add JD',
 '＋ 添加记录': '＋ Add note',
 '＋ 添加附件': '＋ Add attachment',
 '＋ 记录': '＋ Note',
 '＋ 贴入': '＋ Paste',
 '，JD 链接已顺手填上': '; JD link filled in',
 '：还没有版本。可以先把手里的事实/要求丢给我（我归档、记意见），聊到位了说「出一版」；或空着点「⚙ 生成定制简历」直接出首版。想看招聘方视角反馈，出版后点「🔍 评审这版」。': ': no versions '
                                                                                           'yet. Tell me '
                                                                                           'facts or '
                                                                                           'requirements '
                                                                                           "first (I'll file "
                                                                                           'them and note '
                                                                                           'your feedback), '
                                                                                           'then say "make a '
                                                                                           'version"; or '
                                                                                           'just click "⚙ '
                                                                                           'Generate '
                                                                                           'tailored '
                                                                                           'resume". For '
                                                                                           'recruiter-eye '
                                                                                           'feedback, click '
                                                                                           '"🔍 Review this '
                                                                                           'version" '
                                                                                           'afterwards.',
 '：这版评审建议补充的信息（弹药库没有，我不编）——写你手里真实有的，我来归档：': ": the review suggests adding this info (it's not in your "
                                            "Arsenal and I won't invent it) — write what's true and I'll "
                                            'file it:',
 '；不想要的文件点它后面的 ✕ 删除。': '; remove unwanted files with the ✕ next to them.',
 '｜ 参谋 Brief 在时间线（⛶ 全屏读，历史版本在 10-briefs/）': '| Briefs are in the timeline (⛶ to read full screen)',
 '｜ 市场侧：': '| Market side:',
 '🎯 评估匹配': '🎯 Assess fit',
 '🎲 换一题': '🎲 Another problem',
 '💡 复盘建议改': '💡 Debrief suggests',
 '💡 提示（先自己做映射，别急着开）': '💡 Hints (try the mapping yourself first)',
 '📅 排期': '📅 Schedule',
 '📅 近 4 天场次': '📅 Next 4 days',
 '📌 意见：': '📌 Feedback:',
 '📓 今日日记': "📓 Today's diary",
 '🔍 初筛': '🔍 Screen',
 '🔍 评审这版': '🔍 Review this version',
 '🔎 尽调': '🔎 Research',
 '🔴 连续': '🔴',
 '🕵️ 开始尽调': '🕵️ Start research',
 '🖊 我的手记': '🖊 My notes',
 '🖊 手调依据：': '🖊 Adjustment reason:',
 '🗑 删除': '🗑 Delete',
 '🗑 清空重来': '🗑 Start over',
 '🗑 确认删除？': '🗑 Confirm delete?',
 '🤝 内推': '🤝 Referral',
 '🧭 我的复盘': '🧭 My debrief'}



# 指挥中心问候语（与 web.app.GREETINGS 同槽位）
GREETINGS_EN = {
    "dawn": ["Morning. It's barely light and you're already at it.", "Early start. Eat something first — this can wait a bite."],
    "morning": ["Good morning. Pick the one thing that matters most and do it first.",
                "Good morning. You set the pace, not your inbox.",
                "Good morning. One battle at a time — make each one count."],
    "noon": ["Good afternoon. Eat well — the pipeline isn't going anywhere.", "Midday. Resting is part of preparing."],
    "afternoon": ["Good afternoon. Keep a steady pace, one step at a time.", "Good afternoon. Everything you've done counts.",
                  "Good afternoon. Sleepy? Take a walk, then get back to it."],
    "evening": ["Good evening. Today's progress is all on file.", "Good evening. Wrap up and write today down.",
                "Good evening. Every shot you fire builds momentum."],
    "night": ["It's late. One look, then sleep — tomorrow has its own battles.", "Late night. Rest is strength too."],
}
