"""后台的 BI 板块：转化漏斗、功能使用、新用户回访。数据只有账户时间点、用量与「方法 + 路由模板」的使用记录。

漏斗按「走到后面一步，前面各步一定走过」补齐——使用记录是后来才开始采的，老用户早先做过的步骤没有记录。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# (标题, 判定：这人有没有走到这一步) —— 顺序即漏斗顺序
RESUME = {"POST /api/setup/resume"}
SETUP = {"POST /api/setup/basics", "POST /api/setup/skip"}
SOURCING = {"GET /sourcing", "POST /api/sourcing/prefs", "POST /api/sourcing/scan"}
PIPELINE = {"POST /api/proposal/apply", "POST /api/proposal/amend_apply", "POST /api/intake"}

# 常用功能的中文名；没列到的直接显示路由
LABELS = {
    "GET /": "指挥中心", "GET /setup": "首次引导页", "POST /api/setup/resume": "上传简历",
    "POST /api/setup/basics": "填目标薪资与红线", "POST /api/setup/skip": "跳过引导",
    "GET /sourcing": "新机会", "POST /api/sourcing/prefs": "改搜索偏好", "POST /api/sourcing/scan": "立即搜岗",
    "POST /api/sourcing/targets/rescan": "目标公司重搜",
    "POST /api/proposal/apply": "批准机会进作战室", "POST /api/proposal/reject": "拒掉机会",
    "POST /api/proposal/amend_apply": "改后批准", "POST /api/intake": "手动贴机会",
    "GET /pipeline": "作战室", "POST /api/row/update": "更新进展", "POST /api/row/archive": "归档",
    "GET /company/{page_id}": "公司档案", "POST /api/company/research": "公司尽调",
    "POST /api/company/assess": "匹配评估", "POST /api/brief": "面试 brief", "GET /briefs": "brief 列表",
    "GET /playbook": "参谋部", "GET /arsenal": "弹药库", "POST /api/arsenal/save": "编辑弹药库",
    "POST /api/resume/react": "定制简历", "POST /api/resume/eval": "简历评估",
    "POST /api/resume/chat/apply": "简历对话修改", "GET /offers": "offer 对比", "POST /api/comp/research": "薪酬调研",
    "GET /drill": "练兵场", "GET /settings": "设置", "GET /api/export": "导出数据",
}


# 引擎定时作业（job:名字）的中文名
JOB_LABELS = {
    "nightly_sourcing": "夜间搜岗", "morning_report": "晨报", "evening_diary": "日记草稿", "weekly_report": "周报",
    "gmail_scan": "邮件扫描", "calendar_watch": "日历盯面试", "transcript_watch": "面试录音转写",
    "notion_diff_pull": "Notion 同步",
}


def _day(ts: float, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def compute(snap: dict, tz: ZoneInfo, now: float, days: int = 30) -> dict:
    users = {u["email"]: u for u in snap["users"]}
    ev: dict[str, set] = defaultdict(set)                 # 人 → 用过的功能
    active: dict[str, set] = defaultdict(set)             # 人 → 用过的日子
    for e in snap.get("events", []):
        ev[e["email"]].add(e["name"])
        active[e["email"]].add(e["day"])
    for a in snap.get("active_days", []):
        active[a["email"]].add(a["day"])
    for u in snap.get("usage", []):
        active[u["email"]].add(_day(u["at"], tz))
    ai = {r["email"] for r in snap.get("first_ai", []) if r["at"]}

    came = {w["email"] for w in snap.get("waitlist", [])} | {i["email"] for i in snap.get("invites", [])} | set(users)
    steps = [
        ("来过（被拦 / 获邀 / 注册）", lambda e: e in came),
        ("注册", lambda e: e in users),
        ("同意隐私说明", lambda e: e in users and bool(users[e].get("consented_at"))),
        ("打开过应用", lambda e: bool(active[e] or ev[e])),
        ("完成首次引导（传简历 / 填基本信息 / 跳过）", lambda e: bool(ev[e] & (RESUME | SETUP))),
        ("看过新机会", lambda e: bool(ev[e] & SOURCING)),
        ("用上 AI", lambda e: e in ai),
        ("批准第一条机会进作战室", lambda e: bool(ev[e] & PIPELINE)),
    ]                                                     # 「隔天又回来」不是引导的一步，放在回访表
    # 每人走到的最远一步（后一步成立则前面各步都算走过）
    reach = {}
    for e in came:
        k = max((i for i, (_, f) in enumerate(steps) if f(e)), default=0)
        reach[e] = k
    funnel = [(title, sum(1 for k in reach.values() if k >= i)) for i, (title, _) in enumerate(steps)]
    stuck = [sum(1 for k in reach.values() if k == i) for i in range(len(steps))]

    # 功能使用：近 days 天，每个功能多少人用、共多少次
    since = _day(now - days * 86400, tz)
    feat: dict[str, list] = defaultdict(lambda: [set(), 0])
    for e in snap.get("events", []):
        if e["day"] >= since:
            feat[e["name"]][0].add(e["email"])
            feat[e["name"]][1] += e["n"]
    features = sorted(((LABELS.get(k, k), k, len(v[0]), v[1]) for k, v in feat.items()), key=lambda r: (-r[2], -r[3]))

    # 回访：按注册日分组，看注册后第 1 天 / 3 天内 / 7 天内是否又来过
    today = _day(now, tz)
    cohorts: dict[str, list] = defaultdict(list)
    for e, u in users.items():
        cohorts[_day(u["created_at"], tz)].append(e)

    def back(e: str, d0: str, n: int) -> bool:
        start = datetime.strptime(d0, "%Y-%m-%d")
        window = {(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, n + 1)}
        return bool(active[e] & window)

    retention = []
    for d0 in sorted(cohorts, reverse=True)[:14]:
        age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(d0, "%Y-%m-%d")).days
        es = cohorts[d0]
        cells = [(sum(back(e, d0, n) for e in es), len(es)) if age >= n else None for n in (1, 3, 7)]
        retention.append((d0, len(es), cells))
    return {"funnel": funnel, "stuck": stuck, "features": features, "retention": retention,
            "tracked_since": min((e["day"] for e in snap.get("events", [])), default=None)}
