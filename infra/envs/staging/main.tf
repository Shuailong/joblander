# staging 环境。先跑 ../../bootstrap 建好状态桶，再：
#   terraform init -backend-config="bucket=<状态桶>"
#   terraform apply
terraform {
  backend "gcs" {
    prefix = "staging"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

module "platform" {
  source                  = "../../modules/platform"
  project_id              = var.project_id
  region                  = var.region
  env                     = "staging"
  app_domain              = var.app_domain
  site_domain             = var.site_domain
  manage_dns              = var.manage_dns
  extra_dns_records       = var.extra_dns_records
  serve_from              = var.serve_from
  legacy_records          = var.legacy_records
  image_repo              = { project = var.shared_project_id, location = var.region, name = "joblander" }
  deployer_email          = "jl-deployer@${var.shared_project_id}.iam.gserviceaccount.com"
  engine_image            = var.engine_image
  gateway_image           = var.gateway_image
  alert_email             = var.alert_email
  alert_sms               = var.alert_sms
  iap                     = var.iap
  iap_oauth_client_secret = var.iap_oauth_client_secret
  privacy_v2_date         = var.privacy_v2_date
  gateway_settings        = var.gateway_settings
  billing_account         = var.billing_account
  monthly_budget_usd      = var.monthly_budget_usd
  # staging 平时缩到最小：单 zone 的小实例，引擎不常驻
  sql = {
    tier              = "db-custom-1-3840"
    high_availability = false
    disk_gb           = 20
  }
  engine_min_instances = 0
  deletion_protection  = false
}
