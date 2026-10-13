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
variable "monthly_budget_usd" {
  type    = number
  default = 1100
}

variable "privacy_v2_date" {
  description = "隐私说明 v2 生效日（YYYY-MM-DD）"
  type        = string
}
