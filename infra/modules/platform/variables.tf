variable "project_id" {
  description = "GCP 项目 ID（每个环境一个项目：joblander-prod / joblander-staging）"
  type        = string
}

variable "region" {
  description = "唯一区域：新加坡"
  type        = string
  default     = "asia-southeast1"
}

variable "env" {
  description = "环境名：prod 或 staging"
  type        = string
  validation {
    condition     = contains(["prod", "staging"], var.env)
    error_message = "env 只能是 prod 或 staging"
  }
}

variable "app_domain" {
  description = "应用域名，如 app.ailayoff.me"
  type        = string
}

variable "site_domain" {
  description = "官网域名，如 ailayoff.me（www. 前缀自动一并接入）"
  type        = string
}

variable "manage_dns" {
  description = "是否由本模块管理 Cloud DNS 区域（GoDaddy 那边只需把 NS 指过来）"
  type        = bool
  default     = false
}

variable "serve_from" {
  description = "app 与官网的流量指向：legacy = 仍在 Fly / Vercel（切流前），gcp = 本环境的负载均衡器。只在 manage_dns = true 时起作用"
  type        = string
  default     = "legacy"
  validation {
    condition     = contains(["legacy", "gcp"], var.serve_from)
    error_message = "只能是 legacy 或 gcp。"
  }
}

variable "legacy_records" {
  description = "切流前 app / 官网的原记录：{ 域名 = { A = [...], AAAA = [...] } }。用 A / AAAA 而不是 CNAME，切流时才能原地改值"
  type        = map(map(list(string)))
  default     = {}
}

variable "extra_dns_records" {
  description = "原样搬过来的其他记录（Resend 的 DKIM / SPF / MX 等）"
  type = list(object({
    name    = string
    type    = string
    ttl     = number
    rrdatas = list(string)
  }))
  default = []
}

variable "image_repo" {
  description = "共享镜像仓库（infra/bootstrap 建在共享项目里）"
  type        = object({ project = string, location = string, name = string })
}

variable "deployer_email" {
  description = "发布流水线的服务账号（infra/bootstrap 建）：这里给它官网存储桶的写权限与刷 CDN 的权限"
  type        = string
}

variable "engine_image" {
  description = "引擎镜像（engine / worker / sandbox / migrate 共用）。首次可用占位镜像，之后由 CI 发布"
  type        = string
}

variable "gateway_image" {
  description = "网关镜像（gateway / meter 共用）"
  type        = string
}

variable "alert_email" {
  description = "告警邮箱"
  type        = string
}

variable "alert_sms" {
  description = "P1 告警短信号码（E.164，如 +6591234567）；留空则不建短信渠道"
  type        = string
  default     = ""
}

variable "iap" {
  description = "给管理后台 /_gw/admin 加 Identity-Aware Proxy（需要 OAuth 客户端）；members 如 user:a@b.com"
  type = object({
    enabled         = bool
    oauth_client_id = string
    members         = list(string)
  })
  default = {
    enabled         = false
    oauth_client_id = ""
    members         = []
  }
}

variable "iap_oauth_client_secret" {
  description = "IAP 用的 OAuth 客户端密钥"
  type        = string
  default     = ""
  sensitive   = true
}

variable "sql" {
  description = "Cloud SQL 规格。高可用 = 双 zone 自动切换（RPO 0，RTO < 5 分钟）"
  type = object({
    tier              = string
    high_availability = bool
    disk_gb           = number
  })
  default = {
    tier              = "db-custom-2-8192"
    high_availability = true
    disk_gb           = 50
  }
}

variable "gateway_settings" {
  description = <<-EOT
    网关与计量的运营设置（Fly 上原来是 fly secrets 里的这些）：ADMIN_EMAILS（必填）、FEEDBACK_TO、MAIL_FROM、
    DIGEST_AT、MAIL_DAILY_LIMIT、FREE_CREDIT_USD、LOW_BALANCE_USD、SEARCH_PRICE_USD、MONTHLY_BUDGET_USD。值的含义见 cloud/gateway/OPERATIONS.gcp.md
  EOT
  type        = map(string)
  validation {
    condition     = trimspace(lookup(var.gateway_settings, "ADMIN_EMAILS", "")) != ""
    error_message = "gateway_settings 里必须有 ADMIN_EMAILS（否则没人进得了管理后台）。"
  }
}

variable "privacy_v2_date" {
  description = "隐私说明 v2 的版本号兼生效日（YYYY-MM-DD，新加坡时间）。GCP 形态只用 v2；生产填切流当天，改期就改这里再 apply"
  type        = string
  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.privacy_v2_date))
    error_message = "格式为 YYYY-MM-DD。"
  }
}

variable "gateway_min_instances" {
  description = "网关常驻实例数：1 = 发信队列、每日汇总、清理任务随时在跑；0 = 有人访问才起（staging 省钱用）"
  type        = number
  default     = 1
}

variable "meter_min_instances" {
  description = "计量服务常驻实例数"
  type        = number
  default     = 1
}

variable "engine_min_instances" {
  description = "引擎常驻实例数（无冷启动）"
  type        = number
  default     = 1
}

variable "deletion_protection" {
  description = "数据库与服务的删除保护；生产必须开"
  type        = bool
  default     = true
}

variable "billing_account" {
  description = "结算账户 ID（建预算告警用）；留空则不建预算"
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "月预算（美元），50% / 90% / 100% 告警"
  type        = number
  default     = 1100
}
