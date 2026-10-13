# 密钥、服务账号与授权：每个服务一个服务账号，只给它真正要用的权限。

# ---------- Cloud KMS ----------

resource "google_kms_key_ring" "main" {
  name       = local.name
  project    = var.project_id
  location   = var.region
  depends_on = [google_project_service.apis]
}

# 数据盘与托管服务的客户管理密钥（CMEK）：Cloud SQL、存储桶、BigQuery、Pub/Sub、镜像仓库
resource "google_kms_crypto_key" "data" {
  name            = "data"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s" # 90 天
  labels          = local.labels
  lifecycle {
    prevent_destroy = true
  }
}

# 账户数据密钥（DEK）的主密钥（KEK）：引擎信封加密用，不导出
resource "google_kms_crypto_key" "tenant_kek" {
  name            = "tenant-kek"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s"
  labels          = local.labels
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_service_identity" "sql" {
  provider = google-beta
  project  = var.project_id
  service  = "sqladmin.googleapis.com"
}

resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

data "google_storage_project_service_account" "gcs" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

data "google_bigquery_default_service_account" "bq" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key_iam_member" "data_users" {
  for_each = {
    sql    = "serviceAccount:${google_project_service_identity.sql.email}"
    gcs    = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
    bq     = "serviceAccount:${data.google_bigquery_default_service_account.bq.email}"
    pubsub = "serviceAccount:${google_project_service_identity.pubsub.email}"
  }
  crypto_key_id = google_kms_crypto_key.data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ---------- 服务账号 ----------

locals {
  service_accounts = {
    gateway = "网关：登录、同意、后台、转发、签账户令牌"
    meter   = "计量：OpenAI / Tavily 代理与计费"
    engine  = "引擎：多租户 Web 应用"
    worker  = "任务：开通 / 删除 / 迁移账户，按账户跑调度"
    sandbox = "沙箱：跑练兵场用户代码（不授予任何角色）"
    tasks   = "Cloud Scheduler / Cloud Tasks 调用任务服务时用的身份"
    migrate = "数据库迁移作业"
  }
}

resource "google_service_account" "sa" {
  for_each     = local.service_accounts
  project      = var.project_id
  account_id   = "${local.name}-${each.key}"
  display_name = each.value
  depends_on   = [google_project_service.apis]
}

# 运行时都要写日志、指标、链路（沙箱除外：它什么也不该有）
resource "google_project_iam_member" "telemetry" {
  for_each = {
    for pair in setproduct(["gateway", "meter", "engine", "worker", "migrate"],
    ["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"]) :
    "${pair[0]}-${pair[1]}" => { sa = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.sa[each.value.sa].email}"
}

resource "google_kms_crypto_key_iam_member" "tenant_kek" {
  for_each      = toset(["engine", "worker"])
  crypto_key_id = google_kms_crypto_key.tenant_kek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.sa[each.value].email}"
}

# 任务服务建 Cloud Task 时要以 tasks 身份签 OIDC 令牌
resource "google_project_iam_member" "worker_enqueue" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.sa["worker"].email}"
}

resource "google_service_account_iam_member" "worker_acts_as_tasks" {
  service_account_id = google_service_account.sa["tasks"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sa["worker"].email}"
}

# ---------- Secret Manager ----------
# 外部密钥（OpenAI、OAuth、Resend…）只建空壳，值用 gcloud 手动放入，不进 Terraform 状态；
# 内部密钥（会话、账户令牌、数据库密码）由这里生成。

locals {
  external_secrets = ["openai-api-key", "tavily-api-key", "google-oauth-client-id",
  "google-oauth-client-secret", "resend-api-key", "model-prices"]
  generated_secrets = ["session-secret", "tenant-token-secret", "log-salt", "db-gateway-password",
  "db-engine-owner-password", "db-engine-app-password"]
  secret_access = {
    gateway = ["google-oauth-client-id", "google-oauth-client-secret", "session-secret",
    "tenant-token-secret", "resend-api-key", "db-gateway-password", "model-prices", "log-salt"]
    meter   = ["openai-api-key", "tavily-api-key", "model-prices", "db-gateway-password", "log-salt", "resend-api-key"]
    engine  = ["tenant-token-secret", "db-engine-app-password", "log-salt"]
    worker  = ["tenant-token-secret", "db-engine-app-password", "log-salt"]
    migrate = ["db-engine-owner-password", "db-engine-app-password"]
  }
}

resource "google_secret_manager_secret" "s" {
  for_each  = toset(concat(local.external_secrets, local.generated_secrets))
  project   = var.project_id
  secret_id = "${local.name}-${each.value}"
  labels    = local.labels
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "random_password" "generated" {
  for_each = toset(local.generated_secrets)
  length   = 48
  special  = false
}

resource "google_secret_manager_secret_version" "generated" {
  for_each    = toset(local.generated_secrets)
  secret      = google_secret_manager_secret.s[each.value].id
  secret_data = random_password.generated[each.value].result
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each = {
    for pair in flatten([for sa, names in local.secret_access : [for n in names : { sa = sa, name = n }]]) :
    "${pair.sa}-${pair.name}" => pair
  }
  project   = var.project_id
  secret_id = google_secret_manager_secret.s[each.value.name].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa[each.value.sa].email}"
}
