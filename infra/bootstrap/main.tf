# 一次性：建 Terraform 状态桶（开版本控制）与发布流水线用的服务账号。
# 用运营者本人的凭据跑：gcloud auth application-default login && terraform apply
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
  }
}

variable "project_id" {
  description = "放状态桶与 CI 的项目（jl-shared）"
  type        = string
}

variable "region" {
  type    = string
  default = "asia-southeast1"
}

variable "deploy_projects" {
  description = "流水线要部署到的项目（jl-staging、jl-prod）"
  type        = list(string)
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "apis" {
  for_each           = toset(["storage.googleapis.com", "cloudbuild.googleapis.com", "iam.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "tf_state" {
  name                        = "${var.project_id}-tf-state"
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning {
    enabled = true
  }
  lifecycle {
    prevent_destroy = true
  }
}

# Cloud Build 发布用的身份：能推镜像、部署 Cloud Run、跑迁移作业；不能改 IAM 与密钥
resource "google_service_account" "deployer" {
  account_id   = "jl-deployer"
  display_name = "joblander CI 发布"
}

resource "google_project_iam_member" "deployer" {
  for_each = {
    for pair in setproduct(var.deploy_projects, ["roles/run.developer", "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser", "roles/storage.objectAdmin", "roles/logging.logWriter"]) :
    "${pair[0]}-${pair[1]}" => { project = pair[0], role = pair[1] }
  }
  project = each.value.project
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

output "state_bucket" {
  value = google_storage_bucket.tf_state.name
}

output "deployer" {
  value = google_service_account.deployer.email
}
