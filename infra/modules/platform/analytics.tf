# BI（对应方案「BI 与数据」）：BigQuery 三层数据集 + 行为事件经 Pub/Sub 直写。
# 网关元数据的 Datastream 同步需要在网关库里建 publication 与复制槽，等网关切到 Cloud SQL 后再开
# （见 infra/README.md「BI：Datastream」）。

resource "google_bigquery_dataset" "layers" {
  for_each      = toset(["raw", "core", "mart"])
  dataset_id    = "jl_${var.env}_${each.value}"
  project       = var.project_id
  location      = var.region
  friendly_name = "joblander ${var.env} ${each.value}"
  labels        = local.labels
  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.data.id
  }
  depends_on = [google_kms_crypto_key_iam_member.data_users]
}

# 行为事件：只采没关开关的用户；只有路由模板、动作类型、结果、耗时、城市级位置，不含任何文字内容
resource "google_pubsub_topic" "events" {
  name         = "${local.name}-product-events"
  project      = var.project_id
  kms_key_name = google_kms_crypto_key.data.id
  labels       = local.labels
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_kms_crypto_key_iam_member.data_users]
}

resource "google_pubsub_topic_iam_member" "events_publishers" {
  for_each = toset(["gateway", "engine"])
  project  = var.project_id
  topic    = google_pubsub_topic.events.name
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

resource "google_bigquery_table" "events" {
  dataset_id          = google_bigquery_dataset.layers["raw"].dataset_id
  table_id            = "product_events"
  project             = var.project_id
  deletion_protection = var.deletion_protection
  labels              = local.labels
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.data.id # 与数据集默认的 CMEK 一致（不写的话每次 plan 都要重建表）
  }
  time_partitioning {
    type          = "DAY"
    field         = "publish_time"
    expiration_ms = 34190000000 # 约 13 个月（保留期限见隐私说明 v2）
  }
  schema = jsonencode([
    { name = "subscription_name", type = "STRING", mode = "NULLABLE" },
    { name = "message_id", type = "STRING", mode = "NULLABLE" },
    { name = "publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "data", type = "JSON", mode = "NULLABLE" },
    { name = "attributes", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_dataset_iam_member" "pubsub_writer" {
  dataset_id = google_bigquery_dataset.layers["raw"].dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_project_service_identity.pubsub.email}"
}

resource "google_pubsub_subscription" "events_to_bq" {
  name    = "${local.name}-product-events-bq"
  project = var.project_id
  topic   = google_pubsub_topic.events.id
  bigquery_config {
    table          = "${var.project_id}.${google_bigquery_dataset.layers["raw"].dataset_id}.${google_bigquery_table.events.table_id}"
    write_metadata = true
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_writer]
}

# 关掉开关的用户：网关领头实例每天用 DML 把他的行为数据从原始层删掉（gw/events.py Sweeper）
resource "google_project_iam_member" "gateway_bq_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.sa["gateway"].email}"
}

resource "google_bigquery_table_iam_member" "gateway_events_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.layers["raw"].dataset_id
  table_id   = google_bigquery_table.events.table_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.sa["gateway"].email}"
}
