# 入口：一个全球外部应用负载均衡器。
#   app.ailayoff.me          → gateway（/_gw/admin 走 IAP，若启用）
#   ailayoff.me / www        → 官网存储桶 + Cloud CDN；/_pv（自有页面埋点）→ gateway
# Cloud Armor 挡常见攻击与登录口爆破；地理位置由负载均衡器以请求头告诉网关（不再需要离线 IP 库）。

resource "google_compute_global_address" "lb" {
  name       = "${local.name}-lb-ip"
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

resource "google_compute_region_network_endpoint_group" "gateway" {
  name                  = "${local.name}-gateway-neg"
  project               = var.project_id
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.gateway.name
  }
}

resource "google_compute_security_policy" "edge" {
  name    = "${local.name}-armor"
  project = var.project_id
  type    = "CLOUD_ARMOR"

  adaptive_protection_config {
    layer_7_ddos_defense_config {
      enable = true
    }
  }

  # OWASP 常见攻击（敏感度 1：误报最少的一档）
  dynamic "rule" {
    for_each = {
      1000 = "sqli-v33-stable"
      1001 = "xss-v33-stable"
      1002 = "lfi-v33-stable"
      1003 = "rfi-v33-stable"
      1004 = "rce-v33-stable"
      1005 = "scannerdetection-v33-stable"
      1006 = "protocolattack-v33-stable"
    }
    content {
      priority = rule.key
      action   = "deny(403)"
      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${rule.value}', {'sensitivity': 1})"
        }
      }
      description = rule.value
    }
  }

  # 登录口按 IP 限流：每分钟 60 次
  rule {
    priority    = 2000
    action      = "throttle"
    description = "login rate limit"
    match {
      expr {
        expression = "request.path.startsWith('/auth/')"
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 60
        interval_sec = 60
      }
    }
  }

  # 全站按 IP 兜底限流：每分钟 1200 次（正常使用远低于此）
  rule {
    priority    = 2100
    action      = "throttle"
    description = "per-IP ceiling"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 1200
        interval_sec = 60
      }
    }
  }

  rule {
    priority    = 2147483647
    action      = "allow"
    description = "default allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

locals {
  # 地理位置：国家、省份、城市；网关据此记录城市级位置（隐私 v2）
  geo_headers = ["X-Client-Geo-Location:{client_region},{client_region_subdivision},{client_city}"]
}

resource "google_compute_backend_service" "gateway" {
  name                   = "${local.name}-gateway-be"
  project                = var.project_id
  load_balancing_scheme  = "EXTERNAL_MANAGED"
  protocol               = "HTTPS"
  security_policy        = google_compute_security_policy.edge.id
  custom_request_headers = local.geo_headers
  backend {
    group = google_compute_region_network_endpoint_group.gateway.id
  }
  log_config {
    enable      = true # 排障用；30 天过期、只有运维可读（隐私说明 v2 已写明）
    sample_rate = 1.0
  }
}

# 管理后台：同一个网关服务，多一道 Identity-Aware Proxy
resource "google_compute_backend_service" "admin" {
  count                  = var.iap.enabled ? 1 : 0
  name                   = "${local.name}-admin-be"
  project                = var.project_id
  load_balancing_scheme  = "EXTERNAL_MANAGED"
  protocol               = "HTTPS"
  security_policy        = google_compute_security_policy.edge.id
  custom_request_headers = local.geo_headers
  backend {
    group = google_compute_region_network_endpoint_group.gateway.id
  }
  iap {
    enabled              = true
    oauth2_client_id     = var.iap.oauth_client_id
    oauth2_client_secret = var.iap_oauth_client_secret
  }
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_iap_web_backend_service_iam_member" "admins" {
  for_each            = var.iap.enabled ? toset(var.iap.members) : toset([])
  project             = var.project_id
  web_backend_service = google_compute_backend_service.admin[0].name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.value
}

resource "google_compute_backend_bucket" "site" {
  name        = "${local.name}-site-be"
  project     = var.project_id
  bucket_name = google_storage_bucket.site.name
  enable_cdn  = true
  cdn_policy {
    cache_mode        = "CACHE_ALL_STATIC"
    default_ttl       = 3600
    max_ttl           = 86400
    client_ttl        = 600
    negative_caching  = true
    serve_while_stale = 86400
  }
}

resource "google_compute_url_map" "https" {
  name            = "${local.name}-https"
  project         = var.project_id
  default_service = google_compute_backend_bucket.site.id

  host_rule {
    hosts        = [var.app_domain]
    path_matcher = "app"
  }
  host_rule {
    hosts        = [var.site_domain, "www.${var.site_domain}"]
    path_matcher = "site"
  }

  path_matcher {
    name            = "app"
    default_service = google_compute_backend_service.gateway.id
    dynamic "path_rule" {
      for_each = var.iap.enabled ? [1] : []
      content {
        paths   = ["/_gw/admin", "/_gw/admin/*"]
        service = google_compute_backend_service.admin[0].id
      }
    }
  }

  path_matcher {
    name            = "site"
    default_service = google_compute_backend_bucket.site.id
    path_rule {
      paths   = ["/_pv"]
      service = google_compute_backend_service.gateway.id
    }
  }
}

# 证书：Certificate Manager + DNS 授权。授权记录（_acme-challenge 的 CNAME）一加上证书就开始签，
# 不必等 DNS 指过来——切流那一刻证书已经是好的，不会出现「切过去了但证书还在签」的空窗。
locals {
  front_hosts = [var.app_domain, var.site_domain, "www.${var.site_domain}"]
}

resource "google_certificate_manager_dns_authorization" "front" {
  for_each   = toset(local.front_hosts)
  name       = "${local.name}-${replace(each.value, ".", "-")}"
  project    = var.project_id
  domain     = each.value
  labels     = local.labels
  depends_on = [google_project_service.apis]
}

resource "google_certificate_manager_certificate" "main" {
  name    = "${local.name}-cert"
  project = var.project_id
  labels  = local.labels
  managed {
    domains            = local.front_hosts
    dns_authorizations = [for h in local.front_hosts : google_certificate_manager_dns_authorization.front[h].id]
  }
}

resource "google_certificate_manager_certificate_map" "main" {
  name    = "${local.name}-certs"
  project = var.project_id
  labels  = local.labels
}

resource "google_certificate_manager_certificate_map_entry" "front" {
  for_each     = toset(local.front_hosts)
  name         = "${local.name}-${replace(each.value, ".", "-")}"
  project      = var.project_id
  map          = google_certificate_manager_certificate_map.main.name
  hostname     = each.value
  certificates = [google_certificate_manager_certificate.main.id]
  labels       = local.labels
}

resource "google_compute_target_https_proxy" "https" {
  name            = "${local.name}-https-proxy"
  project         = var.project_id
  url_map         = google_compute_url_map.https.id
  certificate_map = "//certificatemanager.googleapis.com/${google_certificate_manager_certificate_map.main.id}"
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "${local.name}-https"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.lb.id
  port_range            = "443"
  target                = google_compute_target_https_proxy.https.id
}

resource "google_compute_url_map" "http_redirect" {
  name    = "${local.name}-http-redirect"
  project = var.project_id
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "http" {
  name    = "${local.name}-http-proxy"
  project = var.project_id
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  name                  = "${local.name}-http"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.lb.id
  port_range            = "80"
  target                = google_compute_target_http_proxy.http.id
}

# ---------- Cloud DNS（可选：GoDaddy 把 NS 指过来即可） ----------
# 先托管、后切流：serve_from = legacy 时 app / 官网仍指向 Fly 与 Vercel（原样搬过来的记录），
# NS 指过来、全网生效之后，切流那一刻把 serve_from 改成 gcp 再 apply——只改记录的值，TTL 300 秒。
# 两种状态下 A 记录同名同类型，Terraform 原地改值，不会先删后建。
locals {
  front_records = merge([
    for h in local.front_hosts : var.serve_from == "gcp"
    ? { "${h}/A" = { name = h, type = "A", rrdatas = [google_compute_global_address.lb.address] } }
    : { for t, v in lookup(var.legacy_records, h, {}) : "${h}/${t}" => { name = h, type = t, rrdatas = v } }
  ]...)
}

resource "google_dns_managed_zone" "site" {
  count    = var.manage_dns ? 1 : 0
  name     = replace(var.site_domain, ".", "-")
  project  = var.project_id
  dns_name = "${var.site_domain}."
  labels   = local.labels
  dnssec_config {
    state = "on"
  }
  lifecycle {
    precondition {
      condition     = var.serve_from == "gcp" || alltrue([for h in local.front_hosts : contains(keys(var.legacy_records), h)])
      error_message = "serve_from = legacy 时，legacy_records 必须给出 app、官网与 www 三个域名的原记录（否则托管过来就断）。"
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_dns_record_set" "front" {
  for_each     = var.manage_dns ? local.front_records : {}
  project      = var.project_id
  managed_zone = google_dns_managed_zone.site[0].name
  name         = "${each.value.name}."
  type         = each.value.type
  ttl          = 300
  rrdatas      = each.value.rrdatas
}

# 证书的 DNS 授权记录（不托管 DNS 时见输出 dns_for_registrar，手工加到 GoDaddy）
resource "google_dns_record_set" "acme" {
  for_each     = var.manage_dns ? google_certificate_manager_dns_authorization.front : {}
  project      = var.project_id
  managed_zone = google_dns_managed_zone.site[0].name
  name         = each.value.dns_resource_record[0].name
  type         = each.value.dns_resource_record[0].type
  ttl          = 300
  rrdatas      = [each.value.dns_resource_record[0].data]
}

resource "google_dns_record_set" "extra" {
  for_each     = var.manage_dns ? { for r in var.extra_dns_records : "${r.name}-${r.type}" => r } : {}
  project      = var.project_id
  managed_zone = google_dns_managed_zone.site[0].name
  name         = each.value.name
  type         = each.value.type
  ttl          = each.value.ttl
  rrdatas      = each.value.rrdatas
}

# ---------- 发布流水线：官网同步与刷 CDN（只给这两样，不给整个项目的存储权限） ----------
resource "google_storage_bucket_iam_member" "site_deployer" {
  bucket = google_storage_bucket.site.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.deployer_email}"
}

resource "google_project_iam_custom_role" "cdn_invalidator" {
  project     = var.project_id
  role_id     = "jlCdnInvalidator"
  title       = "joblander 刷新 CDN 缓存"
  permissions = ["compute.urlMaps.get", "compute.urlMaps.invalidateCache", "compute.globalOperations.get"]
}

resource "google_project_iam_member" "deployer_cdn" {
  project = var.project_id
  role    = google_project_iam_custom_role.cdn_invalidator.id
  member  = "serviceAccount:${var.deployer_email}"
}
