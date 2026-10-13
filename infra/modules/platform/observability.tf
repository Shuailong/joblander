# 监控与告警（对应方案「监控与可观测性」「告警与值班」两节）。
# 不设 7×24 值班：P1 推手机（短信 + 邮件），P2 只发邮件；值守时段 08:00–22:00 新加坡时间。

resource "google_monitoring_notification_channel" "email" {
  display_name = "joblander 运维邮箱"
  project      = var.project_id
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "sms" {
  count        = var.alert_sms == "" ? 0 : 1
  display_name = "joblander P1 短信"
  project      = var.project_id
  type         = "sms"
  labels = {
    number = var.alert_sms
  }
  depends_on = [google_project_service.apis]
}

locals {
  p1_channels = concat([google_monitoring_notification_channel.email.id],
  [for c in google_monitoring_notification_channel.sms : c.id])
  p2_channels = [google_monitoring_notification_channel.email.id]
  runbook     = "https://github.com/Shuailong/joblander/blob/main/cloud/gateway/OPERATIONS.gcp.md"
}

# ---------- Uptime 检查（三个地区，每分钟） ----------
resource "google_monitoring_uptime_check_config" "checks" {
  for_each = {
    app  = { host = var.app_domain, path = "/healthz" }
    site = { host = var.site_domain, path = "/" }
  }
  display_name     = "${local.name} ${each.key}"
  project          = var.project_id
  timeout          = "10s"
  period           = "60s"
  selected_regions = ["ASIA_PACIFIC", "EUROPE", "USA_OREGON"]
  http_check {
    path         = each.value.path
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = each.value.host
    }
  }
}

resource "google_monitoring_alert_policy" "uptime" {
  for_each     = google_monitoring_uptime_check_config.checks
  display_name = "[P1] ${each.key} 不可达"
  project      = var.project_id
  combiner     = "OR"
  conditions {
    display_name = "两个以上地区连续失败 3 分钟"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${each.value.uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "180s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }
    }
  }
  notification_channels = local.p1_channels
  documentation {
    content = "网关或官网对外不可达。Runbook：${local.runbook}"
  }
}

# ---------- 日志指标：应用打出的结构化运维事件（joblander/obs.py、isolation.py） ----------
locals {
  log_metrics = {
    isolation_violations = "jsonPayload.event=\"isolation_violation\""
    task_failures        = "jsonPayload.event=\"task_failed\""
    job_failures         = "jsonPayload.event=\"job_failed\""
    upstream_quota       = "jsonPayload.event=\"upstream_error\" AND jsonPayload.kind=\"insufficient_quota\""
    upstream_ratelimit   = "jsonPayload.event=\"upstream_error\" AND jsonPayload.kind=\"rate_limit_exceeded\""
  }
}

resource "google_logging_metric" "m" {
  for_each = local.log_metrics
  name     = "jl_${each.key}"
  project  = var.project_id
  filter   = "resource.type=\"cloud_run_revision\" AND ${each.value}"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
  depends_on = [google_project_service.apis]
}

locals {
  log_alerts = {
    isolation_violations = { level = "P1", threshold = 0, window = "60s",
    doc = "账户隔离违规：出现即启动泄露评估流程（PDPA：确认可通报后 3 个日历日内通报 PDPC）" }
    upstream_quota = { level = "P1", threshold = 0, window = "60s",
    doc = "OpenAI 账户额度耗尽：去 platform.openai.com 充值" }
    upstream_ratelimit = { level = "P2", threshold = 20, window = "900s",
    doc = "OpenAI 限流：频繁出现就升用量档，或调低任务队列并发" }
    task_failures = { level = "P2", threshold = 10, window = "3600s",
    doc = "用户任务失败偏多：看日志里 task_failed 的 kind 与 error" }
    job_failures = { level = "P2", threshold = 25, window = "3600s",
    doc = "调度作业失败偏多（夜扫 / 晨报 / 轮询）：看 job_failed；必要时暂停任务队列" }
  }
}

resource "google_monitoring_alert_policy" "log_based" {
  for_each     = local.log_alerts
  display_name = "[${each.value.level}] ${each.key}"
  project      = var.project_id
  combiner     = "OR"
  conditions {
    display_name = each.key
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m[each.key].name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.threshold
      duration        = "0s"
      aggregations {
        alignment_period     = each.value.window
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
  notification_channels = each.value.level == "P1" ? local.p1_channels : local.p2_channels
  documentation {
    content = "${each.value.doc}。Runbook：${local.runbook}"
  }
}

# ---------- Cloud SQL ----------
resource "google_monitoring_alert_policy" "sql_down" {
  display_name = "[P1] Cloud SQL 不可用"
  project      = var.project_id
  combiner     = "OR"
  conditions {
    display_name = "database/up = 0"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/up\" AND resource.type=\"cloudsql_database\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MIN"
      }
    }
  }
  notification_channels = local.p1_channels
  documentation {
    content = "高可用切换通常 1 分钟内自愈；超过 5 分钟按 Runbook 处理。${local.runbook}"
  }
}

resource "google_monitoring_alert_policy" "sql_disk" {
  display_name = "[P2] Cloud SQL 磁盘 > 85%"
  project      = var.project_id
  combiner     = "OR"
  conditions {
    display_name = "disk utilization"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\" AND resource.type=\"cloudsql_database\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.85
      duration        = "600s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
  notification_channels = local.p2_channels
}

# ---------- 可用性 SLO（99.5%，30 天）与错误预算燃烧告警 ----------
resource "google_monitoring_custom_service" "app" {
  service_id   = "${local.name}-app"
  display_name = "joblander ${var.env}"
  project      = var.project_id
}

resource "google_monitoring_slo" "availability" {
  service             = google_monitoring_custom_service.app.service_id
  project             = var.project_id
  slo_id              = "availability"
  display_name        = "可用性 99.5%（非 5xx）"
  goal                = 0.995
  rolling_period_days = 30
  request_based_sli {
    good_total_ratio {
      total_service_filter = join(" AND ", [
        "metric.type=\"loadbalancing.googleapis.com/https/request_count\"",
        "resource.type=\"https_lb_rule\"",
        "resource.label.\"url_map_name\"=\"${google_compute_url_map.https.name}\"",
      ])
      bad_service_filter = join(" AND ", [
        "metric.type=\"loadbalancing.googleapis.com/https/request_count\"",
        "resource.type=\"https_lb_rule\"",
        "resource.label.\"url_map_name\"=\"${google_compute_url_map.https.name}\"",
        "metric.label.\"response_code_class\"=500",
      ])
    }
  }
}

resource "google_monitoring_alert_policy" "burn" {
  for_each = {
    fast = { level = "P1", window = "3600s", rate = 14.4 }
    slow = { level = "P2", window = "21600s", rate = 6 }
  }
  display_name = "[${each.value.level}] 可用性错误预算燃烧（${each.key}）"
  project      = var.project_id
  combiner     = "OR"
  conditions {
    display_name = "burn rate > ${each.value.rate}"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.availability.id}\", \"${each.value.window}\")"
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.rate
      duration        = "0s"
    }
  }
  notification_channels = each.value.level == "P1" ? local.p1_channels : local.p2_channels
  documentation {
    content = "5xx 比例超出预算。先看「服务健康」看板与最近一次发布；坏版本就把流量切回上一个 revision。${local.runbook}"
  }
}

# ---------- 云成本预算 ----------
resource "google_billing_budget" "monthly" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "${local.name} 月预算"
  budget_filter {
    projects = ["projects/${local.number}"]
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }
  all_updates_rule {
    monitoring_notification_channels = local.p2_channels
    disable_default_iam_recipients   = false
  }
}
