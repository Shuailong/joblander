# 计算：五个 Cloud Run 服务 + 迁移作业 + 调度队列。镜像由 CI 发布（Terraform 不跟踪镜像版本）。
#
#   负载均衡器 → gateway ──账户令牌──→ engine ──→ meter（OpenAI / Tavily）
#                   │                    └──→ sandbox（练兵场代码）
#                   └──开通 / 删除 / 迁移──→ worker ←── Cloud Tasks ←── Cloud Scheduler（每分钟扇出）

resource "google_artifact_registry_repository" "images" {
  repository_id = "joblander"
  project       = var.project_id
  location      = var.region
  format        = "DOCKER"
  kms_key_name  = google_kms_crypto_key.data.id
  labels        = local.labels
  depends_on    = [google_kms_crypto_key_iam_member.data_users]
}

locals {
  sql_host = google_sql_database_instance.main.private_ip_address
  secret   = { for k, v in google_secret_manager_secret.s : k => v.secret_id }

  # 引擎与任务服务共用的环境变量（值 / 密钥）
  engine_env = {
    JOBLANDER_MODE          = "multi"
    JOBLANDER_DB_HOST       = local.sql_host
    JOBLANDER_DB_NAME       = "engine"
    JOBLANDER_DB_USER       = "engine_app"
    JOBLANDER_KMS_KEY       = google_kms_crypto_key.tenant_kek.id
    JOBLANDER_BLOB_BUCKET   = google_storage_bucket.tenant_blobs.name
    OPENAI_BASE_URL         = "${local.run_url.meter}/v1"
    JOBLANDER_SEARCH_URL    = "${local.run_url.meter}/v1/search"
    JOBLANDER_SANDBOX_URL   = local.run_url.sandbox
    JOBLANDER_ALLOWED_HOSTS = var.app_domain
  }
  engine_secrets = {
    JOBLANDER_DB_PASSWORD         = "db-engine-app-password"
    JOBLANDER_TENANT_TOKEN_SECRET = "tenant-token-secret"
    JOBLANDER_LOG_SALT            = "log-salt"
  }
  # 运营设置（管理员、发件人、额度…）在前，平台固定项在后（同名时以平台为准）
  gateway_env = merge(var.gateway_settings, {
    GW_MODE      = "gcp"
    PUBLIC_HOST  = var.app_domain
    ENGINE_URL   = local.run_url.engine
    WORKER_URL   = local.run_url.worker
    GW_DB_HOST   = local.sql_host
    GW_DB_NAME   = "gateway"
    GW_DB_USER   = "gateway"
    IDLE_MINUTES = "0"
  })
  # 隐私 v2：生效日、会话事件进 Pub/Sub、关掉开关 / 删除账户的人每天从 BigQuery 清理
  gateway_v2_env = {
    PRIVACY_V2_DATE = var.privacy_v2_date
    EVENTS_TOPIC    = google_pubsub_topic.events.id
    EVENTS_TABLE    = "${var.project_id}.${google_bigquery_dataset.layers["raw"].dataset_id}.${google_bigquery_table.events.table_id}"
  }
  gateway_secrets = {
    GW_DB_PASSWORD                = "db-gateway-password"
    GOOGLE_CLIENT_ID              = "google-oauth-client-id"
    GOOGLE_CLIENT_SECRET          = "google-oauth-client-secret"
    SESSION_SECRET                = "session-secret"
    JOBLANDER_TENANT_TOKEN_SECRET = "tenant-token-secret"
    RESEND_API_KEY                = "resend-api-key"
    MODEL_PRICES                  = "model-prices"
    JOBLANDER_LOG_SALT            = "log-salt"
  }
  vpc_egress = {
    network    = google_compute_network.vpc.id
    subnetwork = google_compute_subnetwork.run.id
  }
}

# ---------- gateway：公网入口（只接负载均衡器的流量） ----------
resource "google_cloud_run_v2_service" "gateway" {
  name                = "${local.name}-gateway"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = var.deletion_protection
  # 入口只接负载均衡器；鉴权由网关自己的登录态负责，所以不做 IAM 调用校验
  # （比给 allUsers 授权干净：组织开了「域限制共享」也不受影响）
  invoker_iam_disabled = true
  labels               = local.labels

  template {
    service_account                  = google_service_account.sa["gateway"].email
    max_instance_request_concurrency = 80
    timeout                          = "300s"
    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_egress.network
        subnetwork = local.vpc_egress.subnetwork
      }
    }
    containers {
      image = var.gateway_image
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = false # 发信队列与每日汇总在请求之外跑（只在领头实例上）
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = merge(local.gateway_env, local.gateway_v2_env, { GW_ROLE = "web" })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.gateway_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret[env.value]
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, annotations]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------- meter：计量代理，唯一持有上游 key ----------
resource "google_cloud_run_v2_service" "meter" {
  name                = "${local.name}-meter"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.deletion_protection
  labels              = local.labels

  template {
    service_account                  = google_service_account.sa["meter"].email
    max_instance_request_concurrency = 80
    timeout                          = "900s" # 长生成（reasoning=high）可能十分钟
    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_egress.network
        subnetwork = local.vpc_egress.subnetwork
      }
    }
    containers {
      image = var.gateway_image
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      dynamic "env" {
        for_each = merge(var.gateway_settings, { GW_ROLE = "meter", GW_MODE = "gcp", GW_DB_HOST = local.sql_host,
        GW_DB_NAME = "gateway", GW_DB_USER = "gateway" })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = {
          GW_DB_PASSWORD     = "db-gateway-password"
          OPENAI_API_KEY     = "openai-api-key"
          TAVILY_API_KEY     = "tavily-api-key"
          MODEL_PRICES       = "model-prices"
          JOBLANDER_LOG_SALT = "log-salt"
          RESEND_API_KEY     = "resend-api-key" # 预算 70% / 90% / 100% 与 OpenAI 失败的告警邮件
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret[env.value]
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, annotations]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------- engine：多租户 Web 应用（CPU 常驻：用户发起的长任务在请求结束后继续跑） ----------
resource "google_cloud_run_v2_service" "engine" {
  name                = "${local.name}-engine"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.deletion_protection
  labels              = local.labels

  template {
    service_account                  = google_service_account.sa["engine"].email
    max_instance_request_concurrency = 40
    timeout                          = "300s"
    scaling {
      min_instance_count = var.engine_min_instances
      max_instance_count = 10
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_egress.network
        subnetwork = local.vpc_egress.subnetwork
      }
    }
    containers {
      image = var.engine_image
      resources {
        limits            = { cpu = "2", memory = "4Gi" }
        cpu_idle          = false
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = merge(local.engine_env, { JOBLANDER_ROLE = "engine", JOBLANDER_EVENTS_TOPIC = google_pubsub_topic.events.id })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.engine_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret[env.value]
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, annotations]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------- worker：内部接口与按账户调度 ----------
resource "google_cloud_run_v2_service" "worker" {
  name                = "${local.name}-worker"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.deletion_protection
  labels              = local.labels

  template {
    service_account                  = google_service_account.sa["worker"].email
    max_instance_request_concurrency = 10
    timeout                          = "1800s" # 单个账户的夜扫最长 30 分钟
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_egress.network
        subnetwork = local.vpc_egress.subnetwork
      }
    }
    containers {
      image = var.engine_image
      resources {
        limits = { cpu = "2", memory = "4Gi" }
      }
      dynamic "env" {
        for_each = merge(local.engine_env, {
          JOBLANDER_ROLE        = "worker"
          JOBLANDER_TASKS_QUEUE = google_cloud_tasks_queue.jobs.id
          JOBLANDER_WORKER_URL  = local.run_url.worker
          JOBLANDER_TASKS_SA    = google_service_account.sa["tasks"].email
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.engine_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret[env.value]
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, annotations]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------- sandbox：跑用户代码。无角色的服务账号、无密钥、出网被防火墙拒绝 ----------
resource "google_cloud_run_v2_service" "sandbox" {
  name                = "${local.name}-sandbox"
  project             = var.project_id
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.deletion_protection
  labels              = local.labels

  template {
    service_account = google_service_account.sa["sandbox"].email
    # 第二代执行环境 = 每个实例一台 microVM；并发 1 = 一台 microVM 同时只跑一个人的代码。
    # 与 GKE 的 microVM Sandbox（Kata）是同一种隔离原语，但不需要为此养一个集群。
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 1
    timeout                          = "60s"
    scaling {
      min_instance_count = 0
      max_instance_count = 20
    }
    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = local.vpc_egress.network
        subnetwork = local.vpc_egress.subnetwork
        tags       = ["jl-sandbox"]
      }
    }
    containers {
      image = var.engine_image
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      env {
        name  = "JOBLANDER_ROLE"
        value = "sandbox"
      }
      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version, annotations]
  }
}

# ---------- 服务之间谁能调谁（Cloud Run IAM）----------
locals {
  invokers = {
    "engine-by-gateway" = { service = "engine", sa = "gateway" }
    "worker-by-gateway" = { service = "worker", sa = "gateway" }
    "worker-by-tasks"   = { service = "worker", sa = "tasks" }
    "meter-by-engine"   = { service = "meter", sa = "engine" }
    "meter-by-worker"   = { service = "meter", sa = "worker" }
    "sandbox-by-engine" = { service = "sandbox", sa = "engine" }
    "sandbox-by-worker" = { service = "sandbox", sa = "worker" }
  }
  run_services = {
    gateway = google_cloud_run_v2_service.gateway
    meter   = google_cloud_run_v2_service.meter
    engine  = google_cloud_run_v2_service.engine
    worker  = google_cloud_run_v2_service.worker
    sandbox = google_cloud_run_v2_service.sandbox
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  for_each = local.invokers
  project  = var.project_id
  location = var.region
  name     = local.run_services[each.value.service].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.sa[each.value.sa].email}"
}


# ---------- 调度：每分钟给每个账户投递一轮 ----------
resource "google_cloud_tasks_queue" "jobs" {
  name     = "${local.name}-jobs"
  project  = var.project_id
  location = var.region
  rate_limits {
    max_dispatches_per_second = 5 # 夜扫削峰：同一时刻最多 20 个账户在跑
    max_concurrent_dispatches = 20
  }
  retry_config {
    max_attempts = 1 # 失败的这一轮不重放：下一分钟的轮次自然补上
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_scheduler_job" "fanout" {
  name             = "${local.name}-fanout"
  project          = var.project_id
  region           = var.region
  schedule         = "* * * * *"
  time_zone        = "Asia/Singapore"
  attempt_deadline = "120s"
  http_target {
    http_method = "POST"
    uri         = "${local.run_url.worker}/_internal/scheduler/fanout"
    oidc_token {
      service_account_email = google_service_account.sa["tasks"].email
      audience              = local.run_url.worker
    }
  }
  depends_on = [google_project_service.apis]
}

# ---------- 迁移作业：每次发布前以表所有者身份跑一次 ----------
resource "google_cloud_run_v2_job" "migrate" {
  name                = "${local.name}-migrate"
  project             = var.project_id
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.labels
  template {
    task_count = 1
    template {
      service_account = google_service_account.sa["migrate"].email
      max_retries     = 0
      timeout         = "600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.vpc_egress.network
          subnetwork = local.vpc_egress.subnetwork
        }
      }
      containers {
        image = var.engine_image
        env {
          name  = "JOBLANDER_ROLE"
          value = "migrate"
        }
        env {
          name  = "JOBLANDER_DB_HOST"
          value = local.sql_host
        }
        env {
          name  = "JOBLANDER_DB_NAME"
          value = "engine"
        }
        env {
          name  = "JOBLANDER_DB_USER"
          value = "engine_owner"
        }
        env {
          name = "JOBLANDER_DB_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = local.secret["db-engine-owner-password"]
              version = "latest"
            }
          }
        }
        env {
          name = "JOBLANDER_APP_DB_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = local.secret["db-engine-app-password"]
              version = "latest"
            }
          }
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# ---------- 切流（Fly → GCP，deploy/gcp/cutover.py 调用）与管理命令 ----------
# cutover：把 Fly 卷的打包导入引擎账户并逐文件比对（引擎镜像，任务服务的服务账号：库、密钥、大文件桶都有权限）
resource "google_cloud_run_v2_job" "cutover" {
  name                = "${local.name}-cutover"
  project             = var.project_id
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.labels
  template {
    task_count = 1
    template {
      service_account = google_service_account.sa["worker"].email
      max_retries     = 0
      timeout         = "14400s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.vpc_egress.network
          subnetwork = local.vpc_egress.subnetwork
        }
      }
      containers {
        image = var.engine_image
        resources {
          limits = { cpu = "2", memory = "4Gi" }
        }
        dynamic "env" {
          for_each = merge(local.engine_env, { JOBLANDER_ROLE = "cutover" })
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.engine_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = local.secret[env.value]
                version = "latest"
              }
            }
          }
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}

# gw-cutover：Fly 网关库 → 本环境网关库；gw-cli：管理命令（邀请、加额度、维护模式……），参数在执行时给
resource "google_cloud_run_v2_job" "gateway_tool" {
  for_each            = { "gw-cutover" = "gw.cutover", "gw-cli" = "gw.cli" }
  name                = "${local.name}-${each.key}"
  project             = var.project_id
  location            = var.region
  deletion_protection = var.deletion_protection
  labels              = local.labels
  template {
    task_count = 1
    template {
      service_account = google_service_account.sa["gateway"].email
      max_retries     = 0
      timeout         = "3600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = local.vpc_egress.network
          subnetwork = local.vpc_egress.subnetwork
        }
      }
      containers {
        image   = var.gateway_image
        command = ["python", "-m", each.value]
        resources {
          limits = { cpu = "1", memory = "2Gi" }
        }
        dynamic "env" {
          for_each = merge(local.gateway_env, local.gateway_v2_env)
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.gateway_secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = local.secret[env.value]
                version = "latest"
              }
            }
          }
        }
      }
    }
  }
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_secret_manager_secret_iam_member.access]
}
