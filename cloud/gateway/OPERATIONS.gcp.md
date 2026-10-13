# 云端运维手册（GCP 版）

给运营者自己看的速查。**切流（Fly → GCP）之后用这份**；Fly 时期的 [OPERATIONS.md](OPERATIONS.md) 在 Fly 下线后删掉。
基础设施第一次怎么搭见 [infra/README.md](../../infra/README.md)；为什么这么设计见技术方案（Claude Docs）。
文中 `$T` = `deploy/gcp/cutover.py`，`gwcli` = `deploy/gcp/gwcli.sh`。

## 一页看懂

| 东西 | 在哪 |
|---|---|
| 环境 | 生产 `jl-prod`、预发 `jl-staging`，都在 `asia-southeast1`（新加坡）；镜像与 Terraform 状态在 `jl-shared` |
| 入口 | 全球负载均衡器（Cloud Armor、CDN、证书）：`app.ailayoff.me` → `jl-prod-gateway`；`ailayoff.me` / `www` → 官网存储桶 `jl-prod-site`（`/_pv` 埋点转给网关） |
| 服务 | `gateway` 登录、转发、后台 · `meter` 计量（唯一持有 OpenAI / Tavily key）· `engine` 界面与 API（所有账户共享）· `worker` 开通 / 删除 / 调度 · `sandbox` 练兵场代码（无权限、无出网、每实例一个 microVM） |
| 数据 | Cloud SQL `jl-prod-pg`：`gateway` 库（账户、额度、用量、发信队列…）+ `engine` 库（每账户加密的文件，行级安全）；大文件在 `jl-prod-tenant-blobs` |
| 调度 | Cloud Scheduler `jl-prod-fanout` 每分钟 → Cloud Tasks `jl-prod-jobs` → worker 按账户跑一轮（夜扫、晨报、轮询） |
| 行为数据 | Pub/Sub `jl-prod-product-events` → BigQuery `jl_prod_raw.product_events` |
| 告警 | 邮件发 `alert_email`，P1 另发短信 `alert_sms`。值守 08:00–22:00（新加坡时间）；夜里的告警第二天早上处理（方案已定，不设 7×24） |

## 管理后台与管理命令

后台照旧：**https://app.ailayoff.me/_gw/admin**（`ADMIN_EMAILS` 里的人；开了 IAP 还要过一道 Google 身份验证）。

命令行：Fly 上的 `$GW "python -m gw.cli …"` 换成

```bash
deploy/gcp/gwcli.sh invite a@x.com b@y.com     # 命令与 Fly 时一样，跑完打印输出（一次十几秒）
ENV=staging deploy/gcp/gwcli.sh users          # 预发
```

命令跑在 Cloud Run 作业 `jl-prod-gw-cli` 里（只有它连得上私有 IP 的网关库）。`invite`、`uninvite`、`blocked`、`dismiss`、
`grant`、`users`（第三列是账户号）、`feedback`、`reset`、`maintenance` 都在；`upgrade` 没了——GCP 上没有逐台机器，发布一次全部生效。

## 发布

| 改了什么 | 怎么发 |
|---|---|
| 引擎 / 网关代码 | 推 `main` → Cloud Build（`deploy/gcp/cloudbuild.yaml`）：测试（含 Postgres）→ 两枚镜像 → **自动发 staging** → 冒烟 |
| 上生产 | Cloud Build 里手动跑「生产发布」触发器（`cloudbuild.prod.yaml`，`_TAG` 填 staging 验证过的提交短 SHA；需审批；只在 08:00–22:00）：迁移 → 各服务新版本先接 **10%** 流量 |
| 转正 / 回滚 | 观察 1 小时没告警 → 跑「转正」触发器（`cloudbuild.promote.yaml`）；有问题带 `_ROLLBACK=1` 跑同一个触发器，流量全回上一版 |
| 官网 `site/` | 推 `main` 且改了 `site/` → `cloudbuild.site.yaml` 同步到存储桶并刷 CDN（不再走 Vercel） |
| 基础设施 `infra/` | 本机 `terraform -chdir=infra/envs/prod plan` 看清楚再 `apply`（环境变量、规格、权限、DNS） |

数据库变更只做「先扩后缩」：加表、加列可以；删列、改名等下一个版本——灰度期间新旧版本同时在跑。
引擎库的结构在 `joblander/storage/pg.py` 的 `MIGRATIONS`（发布时迁移作业先跑）；网关库由 `gw/store.py` 启动时就地补齐。

## 配置

运营设置在 `infra/envs/prod/terraform.tfvars` 的 `gateway_settings`（Fly 上的 `fly secrets`），改完 `terraform apply`（各服务出新版本）：

| 名字 | 作用 |
|---|---|
| `ADMIN_EMAILS` | 管理员（逗号分隔）：免邀请、进后台、维护模式下照常进 |
| `FEEDBACK_TO` | 每日汇总的收件人；不设用第一个管理员 |
| `MAIL_FROM` | 给用户发信的发件人（域名须在 Resend 验证过）；不设 = 不给用户发信 |
| `MAIL_DAILY_LIMIT` | 最近 24 小时最多发几封，默认 90（Resend 免费档每天 100） |
| `DIGEST_AT` | 每日汇总几点发，默认 `09:00`；设空 = 不发 |
| `FREE_CREDIT_USD` / `LOW_BALANCE_USD` / `SEARCH_PRICE_USD` | 新用户赠送额度（默认 2）/ 余额提醒线（0.5）/ 每次搜索计费（0.01） |

其他变量：`privacy_v2_date`（隐私说明 v2 生效日；改了会让所有人按新版本再确认一次）、`serve_from`（流量指向，切流用）、
`engine_min_instances`（引擎常驻实例，默认 1）、`sql`（数据库规格）、`iap`（后台的 IAP）。

密钥在 Secret Manager（`jl-prod-<名字>`）。外部密钥（OpenAI、Tavily、Google 登录、Resend、计费单价）自己放值；
内部密钥（会话、账户令牌、日志盐、数据库密码）由 Terraform 生成。换值后要出一个新版本才生效（实例启动时读 `latest`）：

```bash
printf '%s' "$NEW" | gcloud secrets versions add jl-prod-openai-api-key --data-file=- --project jl-prod
gcloud run services update jl-prod-meter --region asia-southeast1 --project jl-prod --update-labels rotated=$(date +%s)
```

**别轮换 `log-salt`**：日志与行为数据里的 `user_key` 都是用它算的，换了就和历史对不上。

## 监控与告警

| 告警 | 级别 | 先做什么 |
|---|---|---|
| 网关 / 官网不可达（两个以上地区连续 3 分钟） | P1 | 看负载均衡器与 `jl-prod-gateway` 日志；刚发过版就回滚 |
| Cloud SQL 不可用 | P1 | 高可用会自动切到备机（通常一两分钟）；不恢复见「恢复」 |
| 账户隔离违规 `isolation_violation` | P1 | 当安全事件处理，见「数据泄露」 |
| OpenAI 额度耗尽 `insufficient_quota` | P1 | 去 platform.openai.com 充值 |
| 可用性错误预算燃烧（快 / 慢） | P1 / P2 | 看 5xx 来自哪个服务；刚发过版就回滚 |
| OpenAI 限流 | P2 | 频繁就升 OpenAI 用量档，或调低 `jl-prod-jobs` 队列并发 |
| 用户任务失败 / 调度作业失败偏多 | P2 | 日志里搜 `task_failed` / `job_failed`，看 `kind` 与 `error` |
| Cloud SQL 磁盘 > 85% | P2 | 调大 `sql.disk_gb` 再 apply（在线扩，不停机） |
| 月预算 50% / 90% / 100% | — | 账单里看哪项涨了 |

后台的「AI 失败」表照旧（计量把失败记进网关库）；Fly 时期的 AI 告警邮件换成了上面两条 OpenAI 告警。

常用日志查询（Logs Explorer，项目 `jl-prod`）：

```
jsonPayload.event="isolation_violation"                   # 隔离违规（kind：rls / decrypt / path / token）
jsonPayload.event="upstream_error"                        # OpenAI / 搜索调用失败
jsonPayload.event=("task_failed" OR "job_failed")         # 用户任务 / 调度作业失败
resource.labels.service_name="jl-prod-gateway" severity>=WARNING
```

日志与行为数据里认人只用 `user_key`（账户号的加盐哈希，不放邮箱）。排查某个人时从邮箱算出来：

```bash
tid=$(deploy/gcp/gwcli.sh users | awk '$1=="a@x.com"{print $3}')
salt=$(gcloud secrets versions access latest --secret jl-prod-log-salt --project jl-prod)
python3 -c 'import hashlib,sys; print(hashlib.sha256(f"{sys.argv[1]}:{sys.argv[2]}".encode()).hexdigest()[:16])' "$salt" "$tid"
```

用户长任务跑在引擎实例的线程里，任务表带心跳：实例被回收时 3 分钟内托盘显示「任务中断，请重试」，不会永远转圈。

## 维护模式

```bash
deploy/gcp/gwcli.sh maintenance on 预计 11:00 恢复   # 只有管理员能进；其他人看「正在搬家」（页面自己刷新），接口回 503
deploy/gcp/gwcli.sh maintenance off
```

维护中停发信、停每日汇总；计量照常（后台任务的 AI 调用照记账）。开关存在网关库里，5 秒内各实例生效。

## 恢复（RPO / RTO 1 小时，值守时段内承诺）

- **数据库误操作 / 损坏**：时间点恢复（最近 7 天内任意时刻）到一台新实例，确认数据对了再把服务指过去：

  ```bash
  gcloud sql instances clone jl-prod-pg jl-prod-pg-r1 --point-in-time 2026-11-03T02:15:00Z --project jl-prod
  ip=$(gcloud sql instances describe jl-prod-pg-r1 --project jl-prod --format='value(ipAddresses[0].ipAddress)')
  R="--region asia-southeast1 --project jl-prod"
  for s in engine worker; do gcloud run services update jl-prod-$s $R --update-env-vars JOBLANDER_DB_HOST=$ip; done
  for s in gateway meter; do gcloud run services update jl-prod-$s $R --update-env-vars GW_DB_HOST=$ip; done
  ```

  作业（`jl-prod-cutover`、`jl-prod-gw-cli` 等）同理用 `gcloud run jobs update … --update-env-vars`。
  事后（不在事故里做）把 Terraform 对齐到新实例，再删旧实例。
- **某个账户要回到过去某个时刻**：还没有现成工具——同样先克隆到那个时刻，再从克隆里导出那个账户（任务服务的
  `/_internal/tenants/{id}/export`，指向克隆库跑一个临时 worker）。少见，真遇到了按此手工做。
- **整区故障**：不做跨区灾备（方案已定，成本优先）。看 https://status.cloud.google.com ，在官网与邮件里说明情况，等恢复。

## 数据泄露（PDPA）

1. 定范围：隔离违规日志（`kind`、时间、`user_key`）、访问日志，判断有没有数据真被别人读到。
2. 止血：必要时开维护模式；轮换相关密钥（账户令牌 `tenant-token-secret`、会话 `session-secret`；后者会让所有人重新登录）。
3. **评估要不要通报**：可能对个人造成重大伤害，或涉及 500 人以上 → 评估确认后 **3 个日历日内**通报 PDPC
   （pdpc.gov.sg 的数据泄露通报表）；重大伤害的情形同时尽快通知受影响的用户。评估本身要尽快做（不超过 30 天）。
4. 留记录：时间线、范围、处理过程、通报与否的理由（决定不通报也要留评估记录）。

## 用户的数据请求

- 查看、导出、删除、关闭行为数据都在设置页自助完成。删除后：数据库备份与存储历史版本里的副本 7 天内过期；
  行为数据由每天的清理任务删掉（1 小时缓冲后）。
- 用户联系你要求代办：经「反馈」或邮件核实是本人，再用 `gwcli reset`（清空空间、保留账户）或请对方在设置页删除。
- 答复要尽快，最迟 30 天（做不到要在 30 天内告诉对方何时能给）。

## 行为数据（隐私说明 v2）

- 在 BigQuery `jl_prod_raw.product_events`，`data` 列是 JSON，`type` 三种：`session`（每人每天一条：IP、城市级位置、设备浏览器）、
  `request`（路由模板、状态码、耗时）、`site_pv`（官网浏览：路径、来源域名、国家，不认人、无 IP）。
- 只采开着开关、过了退出期的人（老用户确认 v2 后 14 天才开始）。关掉开关、删除或重置账户的人：网关每天清理一次，
  1 小时缓冲后从 BigQuery 删掉。完整 IP 90 天后去掉（BigQuery 与网关的「大致所在地」都是）；分区 13 个月后自动过期。
- 看某个人的使用过程：按上面算出的 `user_key` 过滤。**行为数据不与任何内容关联**——这是隐私说明的承诺。

## 费用

预算告警 50% / 90% / 100%。大头：Cloud SQL（高可用两台）、引擎常驻实例、负载均衡器；OpenAI 不在 GCP 账单里。
省钱的旋钮：`engine_min_instances = 0`（代价：冷启动几秒）、`sql.tier` 降档（先在 staging 压测）。

## 切流（Fly → GCP）

一次性。按顺序做，每一步确认了再往下。正式那天的停机时间 ≈ 彩排时 export + upload + import + gateway 的总耗时。

### 提前一周

1. prod 基础设施建好（`infra/README.md` 第 1–9 步）：`serve_from = "legacy"`，`privacy_v2_date` 填切流日，`gateway_settings` 照抄 Fly。
2. 外部密钥放好。Google 登录沿用 Fly 用的 OAuth 客户端最省事（回调地址不变；也可以按 README 第 5 步新建）。想让用户切流后**不用重新登录**，把 Fly 的会话密钥搬过来：
   ```bash
   fly ssh console -a joblander-gw -C "printenv SESSION_SECRET" | tr -d '\r\n' \
     | gcloud secrets versions add jl-prod-session-secret --data-file=- --project jl-prod
   ```
3. 发一版到 prod（真实镜像；同时更新切流作业 `jl-prod-cutover`、`jl-prod-gw-cutover`、`jl-prod-gw-cli` 的镜像）。
4. 手动跑一次官网触发器，把 `site/` 同步到存储桶。
5. Fly 上的网关也换成带维护模式的这一版（切流要用它的 `maintenance` 命令，迁移脚本也认它的格式）：
   `cd cloud/gateway && fly deploy -a joblander-gw --ha=false`，然后 `fly ssh console -a joblander-gw -C "python -m gw.cli maintenance status"` 应回「关」。

### 提前三天：DNS 托管到 Cloud DNS（用户无感）

6. 在 GoDaddy 的 DNS 页面把**所有**记录列出来：app / 官网 / www 三条在 `legacy_records` 里（`fly ips list -a joblander-gw`
   核对 app 的 IP），其余（Resend 的 `send`、`resend._domainkey`、`_dmarc` 等）全部抄进 `extra_dns_records`。apply。
7. 直接问 Cloud DNS，确认和现在一模一样（逐条与 `dig` 公网的结果比）：
   ```bash
   ns=$(terraform -chdir=infra/envs/prod output -json dns_name_servers | jq -r '.[0]')
   for h in app.ailayoff.me ailayoff.me www.ailayoff.me send.ailayoff.me resend._domainkey.ailayoff.me _dmarc.ailayoff.me; do
     for t in A AAAA CNAME TXT; do r=$(dig +short @"$ns" "$h" "$t"); [ -n "$r" ] && echo "$h $t $r"; done; done
   ```
8. GoDaddy → 域名 → 名称服务器 → 改成 `dns_name_servers` 的四个。顶级域的 NS 缓存最长两天；
   `dig NS ailayoff.me +short` 各地都返回 `ns-cloud-…` 就算生效。
9. 证书：授权记录已经在 Cloud DNS 里，NS 生效后一般一小时内签好。**切流前必须是 `ACTIVE`**：
   ```bash
   gcloud certificate-manager certificates describe jl-prod-cert --project jl-prod --format='value(managed.state)'
   ```

### 提前一天：彩排（真数据；用户基本无感）

10. 跑一遍除了切 DNS 以外的全部步骤，每步记下耗时：
   ```bash
   T=deploy/gcp/cutover.py; D=~/jl-cutover
   $T gw-backup --dir $D && $T plan --dir $D
   $T export --dir $D --keep-running        # 逐台冻结几秒打包，机器照常跑；挑人少的时候
   $T upload --dir $D --batch rehearsal
   $T import --batch rehearsal              # 必须全绿；红的看报告，修好后 --only <账户号> 重导
   $T gateway --batch rehearsal
   ```
11. 自测：本机 `/etc/hosts` 加一行 `<负载均衡器 IP> app.ailayoff.me`（`terraform output load_balancer_ip`）。
    用管理员账号登录——库里带过来的维护模式让别人进不来——看自己的数据、跑一个 AI 功能、导出一份。完了删掉那行。

### 切流当天（值守时段，避开 `WAKE_AT` 的几个点，比如工作日上午 10 点）

12. Fly 进维护：`$T maintenance on 预计 11:30 恢复 --where fly`（用户看到「正在搬家」；Fly 的发信、汇总、叫醒都停了）。
13. 正式导出导入——同一批账户号，覆盖彩排的副本：
    ```bash
    $T gw-backup --dir $D && $T plan --dir $D   # 保留彩排分配的账户号；彩排后删了的账户会作废并在导入时清掉
    $T export --dir $D                          # 导完逐台停机
    $T upload --dir $D --batch final
    $T import --batch final                     # 必须全绿
    $T gateway --batch final
    ```
14. 自测（同第 11 步）。
15. 切 DNS：`serve_from = "gcp"`，`terraform apply`（只改三条 A 记录的值、删掉 app 的 AAAA；TTL 300 秒）。
16. GCP 出维护：`$T maintenance off --where gcp`。盯半小时：后台活跃、日志、告警。Fly 保持维护——
    DNS 缓存还没过期的人会看到「正在搬家」，页面自己刷新，几分钟内就到新地址了。

**回滚**（GCP 上还没有用户写入时）：`serve_from = "legacy"` 再 apply，然后 `$T maintenance off --where fly`
（Fly 机器有请求时自动启动）。用户已经在 GCP 上写了东西就别回滚了，往前修。

### 之后

17. Fly 保持维护一周，确认没问题再销毁 `joblander-users` 与 `joblander-gw` 两个应用。迁移桶里的打包 14 天后自动删除，
    想留底就在那之前复制走。
18. 官网：确认 GCP 上的官网与 `/_pv` 埋点正常后，删掉 Vercel 项目，并从 `site/` 去掉 `/_vercel/insights/script.js`。
19. 删掉 `OPERATIONS.md`，这份成为唯一的运维手册。
