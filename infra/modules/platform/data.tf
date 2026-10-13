# 数据：Cloud SQL（网关库 + 引擎库）与存储桶。RPO / RTO 见「可用性与灾备」：
# 高可用双 zone 自动切换；时间点恢复保留 7 天；对象版本 + 软删除 7 天。

resource "google_sql_database_instance" "main" {
  name                = "${local.name}-pg"
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  encryption_key_name = google_kms_crypto_key.data.id
  deletion_protection = var.deletion_protection

  settings {
    edition           = "ENTERPRISE"
    tier              = var.sql.tier
    availability_type = var.sql.high_availability ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.sql.disk_gb
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "19:00" # UTC = 新加坡 03:00，避开夜扫高峰之后
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
      }
    }

    maintenance_window {
      day          = 7  # 周日
      hour         = 20 # UTC = 新加坡周一 04:00
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = false
      record_client_address   = false
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "1000"
    }
  }

  depends_on = [google_service_networking_connection.sql, google_kms_crypto_key_iam_member.data_users]
}

resource "google_sql_database" "db" {
  for_each = toset(["gateway", "engine"])
  name     = each.value
  project  = var.project_id
  instance = google_sql_database_instance.main.name
}

# 网关库的用户与引擎库的表所有者。引擎的应用角色（engine_app）由迁移作业用 SQL 建：
# 经 Cloud SQL 接口建的用户自带 cloudsqlsuperuser，不适合给跑用户请求的服务用。
resource "google_sql_user" "gateway" {
  name     = "gateway"
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  password = random_password.generated["db-gateway-password"].result
}

resource "google_sql_user" "engine_owner" {
  name     = "engine_owner"
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  password = random_password.generated["db-engine-owner-password"].result
}

# ---------- 存储桶 ----------

# 账户的大文件（简历 PDF、录音转写等；内容已按账户加密，桶再套一层 CMEK）
resource "google_storage_bucket" "tenant_blobs" {
  name                        = "${var.project_id}-tenant-blobs"
  project                     = var.project_id
  location                    = upper(var.region)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels
  versioning {
    enabled = true
  }
  soft_delete_policy {
    retention_duration_seconds = 604800 # 7 天
  }
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 7
    }
    action {
      type = "Delete"
    }
  }
  encryption {
    default_kms_key_name = google_kms_crypto_key.data.id
  }
  depends_on = [google_kms_crypto_key_iam_member.data_users]
}

resource "google_storage_bucket_iam_member" "tenant_blobs" {
  for_each = toset(["engine", "worker"])
  bucket   = google_storage_bucket.tenant_blobs.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

# 官网静态页：经负载均衡器 + Cloud CDN 对外，本身就是公开内容
resource "google_storage_bucket" "site" {
  name                        = "${var.project_id}-site"
  project                     = var.project_id
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  labels                      = local.labels
  website {
    main_page_suffix = "index.html"
    not_found_page   = "index.html"
  }
}

resource "google_storage_bucket_iam_member" "site_public" {
  bucket = google_storage_bucket.site.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# 迁移暂存：Fly 卷打包大于 32MB 时先放这里，任务服务从这里读；14 天后自动删除
resource "google_storage_bucket" "migration" {
  name                        = "${var.project_id}-migration"
  project                     = var.project_id
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels
  lifecycle_rule {
    condition {
      age = 14
    }
    action {
      type = "Delete"
    }
  }
  encryption {
    default_kms_key_name = google_kms_crypto_key.data.id
  }
  depends_on = [google_kms_crypto_key_iam_member.data_users]
}

resource "google_storage_bucket_iam_member" "migration_reader" {
  bucket = google_storage_bucket.migration.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.sa["worker"].email}"
}
