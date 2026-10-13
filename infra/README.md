# infra：GCP 上的 joblander（多租户形态）

对应技术方案「目标架构」「可用性与灾备」「安全」「监控」「BI」各节。一个可复用模块
`modules/platform`，按环境实例化：`envs/staging`、`envs/prod`（各自独立项目）。

```
负载均衡器（Cloud Armor · CDN · 证书（Certificate Manager，DNS 授权）· 地理位置头）
  ├─ app.ailayoff.me ──→ gateway ──账户令牌──→ engine ──→ meter（OpenAI / Tavily）
  │                        │                     └──→ sandbox（练兵场代码，无权限、无出网）
  │                        └──开通 / 删除 / 迁移──→ worker ←─ Cloud Tasks ←─ Cloud Scheduler（每分钟）
  └─ ailayoff.me ──→ 官网存储桶（/_pv → gateway）
数据：Cloud SQL（gateway 库 + engine 库，行级安全，按账户加密）· 存储桶（大文件，CMEK）
运维：日志指标 · SLO 99.5% · 燃烧率告警 · Uptime · 预算 ｜ BI：Pub/Sub → BigQuery
```

## 第一次搭建（按顺序）

1. **项目**：建 `joblander-shared`、`joblander-staging`、`joblander-prod` 三个项目并挂上结算账户（控制台或 gcloud）。
2. **状态桶与发布身份**（一次性，用运营者凭据）：
   ```bash
   cd bootstrap
   terraform init && terraform apply -var project_id=joblander-shared \
     -var 'deploy_projects=["joblander-staging","joblander-prod"]'
   ```
3. **环境**（先 staging 后 prod）：
   ```bash
   cd envs/staging
   cp terraform.tfvars.example terraform.tfvars   # 改成真实值：gateway_settings（管理员、发件人…）、
                                                  # privacy_v2_date、DNS（serve_from / legacy_records）
   terraform init -backend-config="bucket=joblander-shared-tf-state"
   terraform apply
   ```
   首次 apply 时服务用的是占位镜像（Google 的 hello 镜像），之后由 CI 发布真实镜像。
   设了 `billing_account`（预算告警）时，先在该项目开 Cloud Billing API：`gcloud services enable cloudbilling.googleapis.com --project <项目>`；
   预算币种 `budget_currency` 要与结算账户一致（Billing - Job Lander 是 SGD）。
4. **填外部密钥**（不进 Terraform 状态）：apply 输出的 `secrets_to_fill` 逐个放值，例如
   ```bash
   printf '%s' "$OPENAI_KEY" | gcloud secrets versions add jl-prod-openai-api-key --data-file=- --project joblander-prod
   ```
   `model-prices` 的值是计费单价 JSON（与 Fly 网关的 `MODEL_PRICES` 相同）。
5. **Google 登录**：在 `joblander-prod` 建 OAuth 客户端（Web 应用），回调地址
   `https://app.ailayoff.me/auth/callback`，客户端 ID / 密钥放进对应密钥。
6. **管理后台的 IAP**（可选）：建 OAuth 品牌与客户端，在 tfvars 里打开 `iap.enabled` 并填成员。
7. **DNS 与证书**：先托管、后切流。`manage_dns = true` 时 Cloud DNS 里的 app / 官网记录按 `serve_from` 指向：
   `legacy` = 仍指 Fly / Vercel（`legacy_records`），`gcp` = 本负载均衡器。GoDaddy 上其余记录（Resend 等）全部抄进
   `extra_dns_records`，核对无误后再把 GoDaddy 的 NS 改成输出里的 `dns_name_servers`。
   证书走 Certificate Manager 的 DNS 授权（`_acme-challenge` 记录自动加进 Cloud DNS；不托管时见输出 `dns_for_registrar`
   手工加），所以**切流前就能签好**，不会出现「切过去了证书还在签」的空窗。整个过程见
   `cloud/gateway/OPERATIONS.gcp.md`「切流」。
8. **数据库迁移**：每次发布前跑一次迁移作业（CI 会自动跑）：
   ```bash
   gcloud run jobs execute jl-prod-migrate --region asia-southeast1 --wait --project joblander-prod
   ```
9. **发布触发器**（控制台 Cloud Build，项目 `joblander-shared`，先连上 GitHub 仓库）：
   主干推送 → `deploy/gcp/cloudbuild.yaml`（自动发 staging）；手动 + 需审批 → `cloudbuild.prod.yaml`（生产灰度 10%）；
   手动 → `cloudbuild.promote.yaml`（转正 / `_ROLLBACK=1` 回滚）；`site/**` 变更 → `cloudbuild.site.yaml`。
   服务账号都用 bootstrap 建的发布身份。

日常运维（发布、配置、告警、恢复、维护模式、切流）见 `cloud/gateway/OPERATIONS.gcp.md`。

## 约定

- **镜像不归 Terraform 管**：服务上的镜像由 CI 发布（`gcloud run deploy`），Terraform 忽略镜像变更，
  两边不会互相覆盖。改环境变量、规格、权限才动 Terraform。
- **不设区域级灾备**（方案已定：成本优先）。区域内：Cloud SQL 高可用 + 时间点恢复 7 天；
  存储桶对象版本 + 软删除 7 天。
- **组织级控制**（组织策略、VPC Service Controls）需要 Cloud Identity 组织，不在本模块里；
  有组织后在组织层单独配置（方案「安全 · 组织与项目」）。
- 网关服务关闭了 IAM 调用校验、入口只接负载均衡器：鉴权由网关自己的登录态负责。
  其余服务一律只接内部流量，谁能调谁见 `run.tf` 的 `invokers`。

## BI：Datastream（网关库 → BigQuery）

网关库切到 Cloud SQL 后再开：在 `gateway` 库里
```sql
CREATE PUBLICATION jl_pub FOR ALL TABLES;
SELECT pg_create_logical_replication_slot('jl_slot', 'pgoutput');
```
并给实例加数据库标志 `cloudsql.logical_decoding=on`，然后在控制台建 Datastream（私有连接 → BigQuery
`jl_prod_raw`）。`feedback.message` 列在流里排除（用户原文不进分析库）。

## 本机校验

```bash
terraform -chdir=envs/prod init -backend=false && terraform -chdir=envs/prod validate
```
