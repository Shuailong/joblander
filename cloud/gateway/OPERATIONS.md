# 云端版运维手册

给运营者自己看的速查。所有管理命令都在网关机器上跑，统一前缀：

```bash
GW='fly ssh console -a joblander-gw -C'
$GW "python -m gw.cli"            # 不带参数 = 打印命令列表
```

## 内测用户管理

### 谁能进

Google 登录后，网关按顺序检查，满足任一条就放行：

1. 在 `ADMIN_EMAILS` 里（管理员，免邀请）
2. 在邀请名单里
3. 以前登录过（已有账户）

都不满足 → 显示「还在内测」，同时记进**被拦名单**；此人**第一次**被拦时给你发一封邮件（发到 `FEEDBACK_TO`，回复直达对方，邮件里附邀请命令）。同一人反复尝试只累加次数，不重复发信。

首次放行会送 `FREE_CREDIT_USD`（默认 $2）AI 额度，并开一台独立机器。

### 常用命令

| 要做什么 | 命令 |
|---|---|
| 邀请（可多个，空格隔开） | `$GW "python -m gw.cli invite a@x.com b@y.com"` |
| 看谁被拦了 | `$GW "python -m gw.cli blocked"` |
| 清掉不认识的被拦记录 | `$GW "python -m gw.cli dismiss a@x.com"` |
| 移出邀请名单 | `$GW "python -m gw.cli uninvite a@x.com"` |
| 看所有用户（状态、余额、已用） | `$GW "python -m gw.cli users"` |
| 加额度（对方须已登录过） | `$GW "python -m gw.cli grant a@x.com 5 朋友内测"` |
| 看最近反馈 | `$GW "python -m gw.cli feedback 20"` |
| 销毁某人机器与数据（**不可恢复**） | `$GW "python -m gw.cli reset a@x.com"` |

要点：

- **邀请后不用通知系统**：对方回到 app.ailayoff.me 重新登录即可。`invite` 会顺手把此人从被拦名单清掉。
- **`uninvite` 不会踢掉已开通的人**：登录过就有账户，账户在就能进。要让人彻底出去，用 `reset`（销毁数据但保留账户与额度）或让对方在设置页「删除账户」。
- **`grant` 之前对方必须登录过一次**：账户是第一次登录时建的。

## 部署

### 只改了网关（`cloud/gateway/`）

```bash
cd cloud/gateway && fly deploy -a joblander-gw --ha=false
```

用户机器不受影响，不用 upgrade。

### 改了引擎（`joblander/`，用户机器跑的那部分）

vN 取比上一次大一的数字（截至 2026-10-05 线上是 v14）：

```bash
fly deploy --build-only --push -c deploy/fly.users.toml --image-label vN .
fly secrets set -a joblander-gw --stage USER_IMAGE=registry.fly.io/joblander-users:vN   # 新用户用新镜像
(cd cloud/gateway && fly deploy -a joblander-gw --ha=false)                              # 让 secret 生效
$GW "python -m gw.cli upgrade registry.fly.io/joblander-users:vN"                       # 老用户换镜像
```

数据在卷上，换镜像不丢。

### 官网（`site/`）

推到 `main` 即自动发布（Vercel）。**不要**用 `vercel --prod`，会弄丢访问统计。发布后确认 `https://ailayoff.me/_vercel/insights/script.js` 返回 200。

## 配置（网关 secrets）

用 `fly secrets set -a joblander-gw KEY=...` 设置，`fly secrets list -a joblander-gw` 只看名字不看值。

| 名字 | 作用 |
|---|---|
| `ADMIN_EMAILS` | 管理员（逗号分隔），免邀请 |
| `FEEDBACK_TO` | 反馈与被拦提醒收件人；不设则用第一个管理员 |
| `RESEND_API_KEY` | 发邮件用；不设则不发信（记录照存，用命令查） |
| `FREE_CREDIT_USD` | 新用户赠送额度，默认 2 |
| `USER_IMAGE` | 新用户机器用的镜像 |
| `USER_MEMORY_MB` | 用户机器内存，默认 1024 |
| `OPENAI_API_KEY` / `TAVILY_API_KEY` | 上游 key（只在网关，用户机器拿到的是计量子 key） |
| `MODEL_PRICES` | 计费单价 JSON |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `SESSION_SECRET` / `PUBLIC_HOST` | 登录与会话 |

## 排障

- **看日志**：`fly logs -a joblander-gw`。访问日志只有「方法 / 类别 / 状态码 / 耗时 / IP」，不含路径与内容（隐私承诺，别改回去）。
  `GET /auth/ 200`（几百毫秒）通常就是有人被拦或登录失败；正常登录是 `302`。
- **某个用户卡在开通**：`users` 看状态与报错；必要时 `reset` 让其下次登录重新开通。
- **备份**：用户卷由 Fly 每天自动快照，保留 5 天。
