variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-southeast1"
}
variable "app_domain" { type = string }
variable "site_domain" { type = string }
variable "manage_dns" {
  type    = bool
  default = false
}
variable "extra_dns_records" {
  type = list(object({
    name    = string
    type    = string
    ttl     = number
    rrdatas = list(string)
  }))
  default = []
}
variable "engine_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello" # 占位：首个 CI 发布后被替换
}
variable "gateway_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}
variable "alert_email" { type = string }
variable "alert_sms" {
  type    = string
  default = ""
}
variable "iap" {
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
  type      = string
  default   = ""
  sensitive = true
}
variable "billing_account" {
  type    = string
  default = ""
}
variable "budget_currency" {
  type    = string
  default = "SGD"
}

variable "monthly_budget_usd" {
  type    = number
  default = 1100
}

variable "privacy_v2_date" {
  description = "隐私说明 v2 生效日（YYYY-MM-DD）"
  type        = string
}

variable "serve_from" {
  description = "app 与官网的流量指向：legacy（切流前）或 gcp"
  type        = string
  default     = "legacy"
}

variable "legacy_records" {
  description = "切流前 app / 官网的原记录（A / AAAA）"
  type        = map(map(list(string)))
  default     = {}
}

variable "gateway_settings" {
  description = "网关与计量的运营设置（ADMIN_EMAILS 必填）"
  type        = map(string)
}

variable "shared_project_id" {
  description = "共享项目（Terraform 状态、镜像仓库、发布流水线）"
  type        = string
  default     = "joblander-shared"
}
