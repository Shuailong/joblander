"""界面英文表：键是中文原文（模板里 _() 包住的那句），值是英文。缺键回落中文。"""

EN: dict[str, str] = {' 和 LinkedIn': ' and LinkedIn',
 ' 失败：': ' failed: ',
 ' 完成': ' done',
 'AI 草稿': 'AI draft',
 'AI 额度': 'AI credit',
 'AI 额度…': 'AI credit…',
 'AI 额度已用完——充值或订阅后继续使用': 'AI credit used up — top up or subscribe to continue',
 'AI 额度已用完——生成类功能暂停。<a href="/_gw/account">查看用量</a>，或找邀请你的朋友加额度。': 'AI credit used up — generation is '
                                                                   'paused. <a href="/_gw/account">See '
                                                                   'usage</a>, or ask the friend who invited '
                                                                   'you for more credit.',
 'Gmail 上次': 'Gmail last run',
 'Gmail 邮箱': 'Gmail',
 'Google 日历': 'Google Calendar',
 'High 战线': 'High priority',
 'JD 附件（可空：PDF/文本——正文进抽取，文件随批准落公司档案）': 'JD attachment (optional: PDF/text — its text is extracted; the file '
                                       'is filed to the company on approval)',
 'LinkedIn 上次': 'LinkedIn last run',
 'LinkedIn 个人主页（供起草内推/触达时引用）': 'Your LinkedIn profile URL (used when drafting referral/outreach messages)',
 'LinkedIn 职位自动搜索': 'Automatic LinkedIn job search',
 'MCF 上次': 'MCF last run',
 'WhatsApp / 猎头消息 / 任意 JD': 'WhatsApp / recruiter messages / any JD',
 'tracker 建行（线索列）+ 建公司档案': 'Creates a pipeline row and a company file',
 '{n} 个岗位': '{n} roles',
 '{n} 件要动': '{n} to act on',
 '{n} 单更新提案等你批（公司页/指挥中心）': '{n} update proposals awaiting your approval',
 '{n} 单等你批': '{n} awaiting approval',
 '{n} 条新线索待决策': '{n} new leads to review',
 '{p} 不存在——检查 config profile.files': '{p} not found — check profile.files in config',
 '↻ 全量刷新': '↻ Refresh all',
 '↻ 扫邮箱': '↻ Scan inbox',
 '↻ 立即搜': '↻ Search now',
 '▤ 战绩素材库（achievement-bank）': '▤ Achievement bank',
 '▸ 现在就做（按序）': '▸ Do now (in order)',
 '⚠️ 弹药库为空——初筛无履历可对照，req_gaps 全部只能标存疑。去「弹药库」页写第一段战绩。': '⚠️ Your Arsenal is empty — screening has nothing to '
                                                       'compare against. Add your first achievements on the '
                                                       'Arsenal page.',
 '✎ 填搜索偏好': '✎ Fill in preferences',
 '✎ 核对偏好': '✎ Check preferences',
 '✎ 编辑': '✎ Edit',
 '三步把 joblander 喂到能用': 'Three steps to get joblander working for you',
 '上传一份旧简历': 'Upload an existing resume',
 '上传并生成弹药库': 'Upload and build Arsenal',
 '上传简历后系统会先猜一组目标岗位并替你搜一轮；也可以直接去填。': "Once you upload a resume we'll guess target roles and run a first "
                                    'search; or fill them in yourself.',
 '上次抓 {a} 提 {b}': 'last run: {a} fetched, {b} proposed',
 '下面这组搜索偏好是根据你的简历猜的': 'These search preferences were guessed from your resume',
 '不能出现在对外材料里的词：内部项目代号、绩效评级、现薪数字……': 'Words that must never appear in anything you send out: internal '
                                    'codenames, performance ratings, current salary…',
 '事件标题': 'Event title',
 '今天': 'Today',
 '今天 {n} 场': '{n} today',
 '今天的感受、判断、要提醒自己的话……': 'How today went, your judgment calls, reminders to yourself…',
 '今天还没有战线事件——打了仗（面试/通话/邮件落档案）之后，这里 21:30 自动出日记草稿。': 'No events today yet — once you log interviews, calls or '
                                                    'emails to a company file, a diary draft appears here at '
                                                    '21:30.',
 '今日到期': 'Due today',
 '从简历生成弹药库': 'Build Arsenal from resume',
 '任何生成的简历、消息草稿里出现这些词都会被拦下。': 'Any generated resume or message draft containing these words is blocked.',
 '任务': 'Task',
 '低匹配 / 未评分（{n} 家）——大概率不值得看，展开确认后批量否决': 'Low fit / unscored ({n} companies) — probably not worth it; expand '
                                        'to confirm and reject in bulk',
 '作战室': 'War Room',
 '作战室排了面试，但日历接下来 7 天没这场': 'An interview is in your War Room but not on your calendar for the next 7 days',
 '你的材料、目标与红线，以及可选功能。': 'Your materials, targets and red lines, plus optional features.',
 '你自己的总结与感受——与 AI 生成的部分分开存放，永不被自动覆盖': 'Your own reflections — stored separately from AI content and never '
                                      'overwritten',
 '例如 250000': 'e.g. 250000',
 '依次拉取已连接的数据源，完成后刷新页面': 'Pull each connected source, then refresh',
 '保存': 'Save',
 '保存偏好': 'Save preferences',
 '保存手记': 'Save notes',
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
 '入池': 'Add to pipeline',
 '入池初筛（req_gaps 对照）、公司页「评估匹配」、能力画像读的都是弹药库——在那里改了战绩，下次评估自动生效，无需任何操作。': 'Lead screening, company fit '
                                                                      'assessment and your capability '
                                                                      'profile all read from the Arsenal — '
                                                                      'edit your achievements there and the '
                                                                      'next assessment picks them up '
                                                                      'automatically.',
 '全天': 'All day',
 '全选': 'Select all',
 '关键词': 'Keywords',
 '功能': 'Features',
 '半自动': 'Manual',
 '原文或 JD 链接粘贴到这里（有附件时可空）': 'Paste the text or a JD link here (optional if you attach a file)',
 '去定稿': 'Finalize',
 '去批': 'Review',
 '去设置求职偏好 →': 'Set search preferences →',
 '参谋部': 'Strategy',
 '取消': 'Cancel',
 '只影响界面文字；AI 生成的内容暂时仍是中文。': 'Affects interface text only; AI-generated content is still in Chinese for now.',
 '可在设置里关': 'can be turned off in Settings',
 '后台任务——点完随便去哪，右下角看进度，完成自动刷新': 'Runs in the background — feel free to navigate away; progress shows '
                               'bottom-right and the page refreshes when done',
 '后天': 'In 2 days',
 '否决': 'Reject',
 '否决中…': 'Rejecting…',
 '否决所选': 'Reject selected',
 '告诉系统你在找什么': 'Tell us what you are looking for',
 '周一': 'Mon',
 '周三': 'Wed',
 '周二': 'Tue',
 '周五': 'Fri',
 '周六': 'Sat',
 '周四': 'Thu',
 '周日': 'Sun',
 '唯一事实来源': 'single source of truth',
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
 '复制原文 →「＋ 贴入」→ 抽取 + 查重 + 评分自动完成': 'Copy the text → "＋ Paste" → extraction, de-dup and scoring happen '
                                   'automatically',
 '失败：': 'Failed: ',
 '字段建议': 'Field suggestion',
 '完成': 'Done',
 '完成（{n} 个源失败）': 'Done ({n} sources failed)',
 '完成，刷新中…': 'Done, refreshing…',
 '定稿入日报': 'Finalize to daily log',
 '对外报价的锚点。Offer 对比按它算差距，屏幕上只显示百分比。': 'Your quoting anchor. Offer comparison measures gaps against it and '
                                     'only shows percentages on screen.',
 '已保存': 'Saved',
 '已入待入池': 'Added to the review queue',
 '已入池': 'Added to pipeline',
 '已关闭': 'Disabled',
 '已否决': 'Rejected',
 '已否决 {n} 条': 'Rejected {n}',
 '已定稿 · ': 'Finalized · ',
 '已定稿入日报': 'Saved to daily log',
 '已开启': 'Enabled',
 '已根据你的简历猜了一组目标岗位和城市，并替你跑了第一轮搜索。去「新机会」核对一下——改准了，之后每晚的搜索和打分都会更准。': 'We guessed target roles and cities from '
                                                                  'your resume and ran a first search for '
                                                                  'you. Check them on New Leads — the more '
                                                                  'accurate they are, the better every '
                                                                  'nightly search and score will be.',
 '已跳过，随时回这里补': 'Skipped — come back here anytime',
 '开始设置': 'Getting started',
 '引擎在线（本机）': 'Engine online (local)',
 '弹药库': 'Arsenal',
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
 '待入池（{n} 岗 · 按公司聚合，已在库公司不出现在这里）': 'To review ({n} roles · grouped by company; companies already in your '
                                   'pipeline are hidden)',
 '待批提案（长在各自属地）': 'Proposals awaiting approval',
 '战线・公司档案・提案・日记 = 实时': 'pipeline, files, proposals, diary = live',
 '所选全部否决——只记账，可反悔': 'Reject all selected — logged, reversible',
 '手记已存进日报': 'Notes saved to daily log',
 '打开弹药库核对 →': 'Review your Arsenal →',
 '打开档案': 'Open file',
 '扫 MyCareersFuture': 'Scan MyCareersFuture',
 '扫描版 PDF 读不出文字；用 Word 或能选中文字的 PDF。': "Scanned PDFs can't be read — use Word or a PDF with selectable text.",
 '扫描邮箱': 'Scan inbox',
 '抽取 → 待入池': 'Extract → review queue',
 '拆分结果不是合法 JSON——重试一次': 'The AI returned an unreadable result — please try again',
 '指挥中心': 'Command Center',
 '按求职偏好每晚搜一次 LinkedIn 公开职位（免登录接口），和 MCF 一起打分入池。接口随时可能被 LinkedIn 调整或限流。': "Searches LinkedIn's public job "
                                                                         'listings nightly using your '
                                                                         'preferences (no login), scored '
                                                                         'alongside MCF. LinkedIn may change '
                                                                         'or rate-limit this at any time.',
 '按详情创建 Google Calendar 事件——这一步就是逐次确认': 'Create the Google Calendar event — this click is your confirmation',
 '排除词': 'Exclude',
 '排除词（命中直接丢弃，不进待入池）': 'Exclude words (matching titles are dropped)',
 '推进': 'Follow up',
 '搜新机会': 'Search new leads',
 '搜索偏好（喂给评分器和搜索源）': 'Search preferences (used for search and scoring)',
 '支持 PDF / Word / Markdown / 纯文本简历': 'Supported: PDF / Word / Markdown / plain-text resumes',
 '改动即刻喂给评分器与搜索源；存私有 workspace，不进代码库。': 'Changes take effect immediately and are stored only in your private '
                                       'workspace.',
 '数据源：': 'Sources:',
 '新机会': 'New Leads',
 '无 High 行': 'No high-priority rows',
 '无逾期 ✅': 'nothing overdue ✅',
 '无面试场次 ✅': 'No interviews ✅',
 '日历事件已创建': 'Calendar event created',
 '日历同步': 'Calendar sync',
 '日期': 'Date',
 '日记草稿就绪——在下方改两句，定稿进参谋部日报': 'Diary draft ready — tweak it below and finalize it into your daily log',
 '时长（分）': 'Duration (min)',
 '时间': 'Time',
 '明天': 'Tomorrow',
 '暂无待决策线索 ✅ 每晚自动搜，有新的会出现在这里。等不及就点上面的「立即搜」。': 'Nothing to review ✅ We search every night and new leads will '
                                             'show up here. Can’t wait? Hit "Search now" above.',
 '来源': 'Source',
 '来源：tracker↔日历每周对账（{n}）——补上时间就能建入 Google 日历，或否决': 'Source: weekly pipeline↔calendar check ({n}) — add the '
                                                   'time to create the event, or reject',
 '每 30 分钟自动一轮，分类闸过滤非机会': 'Every 30 minutes; non-opportunities are filtered out',
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
 '没能从简历里拆出任何条目——换一份文字版简历（不是扫描图片）再试': "Couldn't extract any entries — try a text-based resume (not a scanned "
                                     'image)',
 '没能从简历里认出姓名和联系方式——定制简历的抬头需要它，请在 workspace 的 03-materials/profile.json 补上。': "Couldn't find your name and "
                                                                             'contact details in the resume '
                                                                             '— tailored resumes need them '
                                                                             'for the header. Add them in '
                                                                             '03-materials/profile.json.',
 '活跃战线 {a}/{b} 行': '{a}/{b} active',
 '清除': 'Clear',
 '渠道': 'Channels',
 '现在生成': 'generate it now',
 '目标岗位、城市、关键词和排除项——每晚的搜索和打分按这个来。': 'Target roles, cities, keywords and exclusions — nightly search and '
                                   'scoring follow these.',
 '目标岗位关键词（逗号分隔，MCF / LinkedIn 按这个搜）': 'Target job titles (comma-separated — used to search MCF / LinkedIn)',
 '目标年度总包要填一个正数': 'Target annual total comp must be a positive number',
 '目标年度总包（base + bonus + equity）': 'Target annual total comp (base + bonus + equity)',
 '目标薪资与红线': 'Target pay and red lines',
 '直接在下面改，定稿即入 {d}.md 的「今日日记」段': 'Edit below; finalizing saves it to the diary section of {d}.md',
 '看首轮结果、核对偏好 →': 'See first results and check preferences →',
 '确认建事件': 'Create event',
 '等你批（改/批都在档案页）': ' awaiting your approval (edit/approve on the company page)',
 '简历文字太少——可能是扫描版 PDF，换一份能选中文字的版本': 'Too little text — it may be a scanned PDF; use a version with selectable '
                                   'text',
 '算法题练习，可在线运行代码——偏软件工程岗位。开启后侧栏出现入口。': 'Coding interview practice with in-browser code execution — mainly for '
                                      'software roles. Adds an entry to the sidebar.',
 '系统': 'System',
 '系统会把简历拆成按公司/项目分段的「战绩弹药库」：只搬运简历里写了的事实，不补写、不美化。大约需要一分钟。': 'Your resume is split into an "Arsenal" of '
                                                          'achievements, grouped by company/project. Only '
                                                          'facts that are in your resume are carried over — '
                                                          'nothing added, nothing embellished. Takes about a '
                                                          'minute.',
 '素材=各公司档案今天的战线事件；数据同步、评估重算这类系统动作不入日记。定稿落参谋部日报。': "Built from today's events in your company files (system "
                                                  'actions are left out). Finalized entries go to your daily '
                                                  'log.',
 '红线词（可空，一行一个）': 'Red-line words (optional, one per line)',
 '练兵场': 'Practice',
 '练兵场未开启（设置 → 功能）': 'Practice is off (Settings → Features)',
 '缺失': 'missing',
 '自动': 'Auto',
 '自动搜索已关（可在设置里开）。深链按你的关键词拼好近 24h 搜索——看到好的用「＋ 贴入」丢回来：': 'Automatic search is off (turn it on in Settings). '
                                                       'These links open a last-24h search for your keywords '
                                                       '— paste back anything good with "＋ Paste":',
 '草稿 21:30 自动生成，也可以': 'A draft is generated at 21:30, or you can',
 '草稿已生成': 'Draft generated',
 '薪酬调研（W4）': 'Compensation research',
 '补充偏好': 'Other preferences',
 '补充偏好（自由文本：公司类型、避雷、加分项）': 'Other preferences (free text: company types, deal-breakers, nice-to-haves)',
 '补充材料': 'supporting material',
 '补时间建入日历': 'Add the time to create a calendar event',
 '设置': 'Settings',
 '评分依据 · 弹药库': 'Scored against · Arsenal',
 '评分器实际吃到 {n} 字符（上限 12,000，超出截断）。': 'The scorer reads {n} characters (capped at 12,000).',
 '读不出简历文字——可能是扫描版，换一份能选中文字的版本': "Couldn't read any text — it may be a scanned file; use a version with "
                                'selectable text',
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
 '起草今日日记': "Draft today's diary",
 '跟进更新': 'Follow-up update',
 '进入待入池的时间': 'When it entered the queue',
 '进入指挥中心 →': 'Go to Command Center →',
 '进行中——右下角看进度': 'in progress — see bottom-right',
 '退出登录': 'Sign out',
 '选低匹配': 'Select low-fit',
 '逾期': 'Overdue',
 '逾期 follow-up': 'Overdue follow-ups',
 '重估能力画像': 'Re-assess capability profile',
 '集团冲突：': 'Group conflict: ',
 '面后录入': 'Post-interview notes',
 '面试': 'Interview',
 '首次搜新机会': 'First search for new leads',
 '首轮搜索已经按它跑过了。核对一下关键词和地点——改准了，之后每晚的搜索和打分都会更准。': 'A first search has already run with them. Check the '
                                                'keywords and locations — the more accurate they are, the '
                                                'better every nightly search and score.',
 '（含 LinkedIn Job Alert 邮件）': ' (incl. LinkedIn Job Alert emails)',
 '（日历缓存等 daemon 刷新，最长 30 分钟）': ' (calendar cache refreshes within 30 min)',
 '＋ 贴入': '＋ Paste',
 '📅 近 4 天场次': '📅 Next 4 days',
 '📓 今日日记': "📓 Today's diary",
 '🖊 我的手记': '🖊 My notes'}



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
