variable "project_id" {
  description = "GCP 项目 ID（每个环境一个项目：jl-prod / jl-staging）"
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

variable "privacy_v2_date" {
  description = "隐私说明 v2 的版本号兼生效日（YYYY-MM-DD，新加坡时间）。GCP 形态只用 v2；生产填切流当天，改期就改这里再 apply"
  type        = string
  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.privacy_v2_date))
    error_message = "格式为 YYYY-MM-DD。"
  }
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
