# prod 环境。先跑 ../../bootstrap 建好状态桶，再：
#   terraform init -backend-config="bucket=<状态桶>"
#   terraform apply
terraform {
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 6.10" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 6.10" }
    random      = { source = "hashicorp/random", version = "~> 3.6" }
  }
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

# 只给预算用：请求里指明计费项目（预算 API 不收没有计费项目的个人登录凭据）
provider "google" {
  alias                 = "billing"
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

module "platform" {
  source = "../../modules/platform"
  providers = {
    google         = google
    google-beta    = google-beta
    google.billing = google.billing
    random         = random
  }
  project_id              = var.project_id
  region                  = var.region
  env                     = "prod"
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
  sql = {
    tier              = "db-custom-2-8192"
    high_availability = true
    disk_gb           = 50
  }
  engine_min_instances = 1
  deletion_protection  = true
}
