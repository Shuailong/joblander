# prod 环境。先跑 ../../bootstrap 建好状态桶，再：
#   terraform init -backend-config="bucket=<状态桶>"
#   terraform apply
terraform {
  backend "gcs" {
    prefix = "prod"
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
  env                     = "prod"
  app_domain              = var.app_domain
  site_domain             = var.site_domain
  manage_dns              = var.manage_dns
  extra_dns_records       = var.extra_dns_records
  engine_image            = var.engine_image
  gateway_image           = var.gateway_image
  alert_email             = var.alert_email
  alert_sms               = var.alert_sms
  iap                     = var.iap
  iap_oauth_client_secret = var.iap_oauth_client_secret
  privacy_v2_date         = var.privacy_v2_date
  billing_account         = var.billing_account
  monthly_budget_usd      = var.monthly_budget_usd
  sql = {
    tier              = "db-custom-2-8192"
    high_availability = true
    disk_gb           = 50
  }
  engine_min_instances = 1
  deletion_protection  = true
}
