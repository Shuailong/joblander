# 一次性：建 Terraform 状态桶（开版本控制）、共用的镜像仓库与发布流水线用的服务账号。
# 各环境的 Cloud Run 从这个仓库拉镜像（授权在 modules/platform 里，环境自己给自己的服务代理授权）。
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
  description = "放状态桶与 CI 的项目（joblander-shared）"
  type        = string
}

variable "region" {
  type    = string
  default = "asia-southeast1"
}

variable "deploy_projects" {
  description = "流水线要部署到的项目（joblander-staging、joblander-prod）"
  type        = list(string)
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "apis" {
  for_each = toset(["storage.googleapis.com", "cloudbuild.googleapis.com", "iam.googleapis.com",
  "artifactregistry.googleapis.com", "logging.googleapis.com"])
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

# 两个环境共用一套镜像：staging 验证过的同一个镜像原样发到 prod
resource "google_artifact_registry_repository" "images" {
  repository_id = "joblander"
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# Cloud Build 发布用的身份：能推镜像、部署 Cloud Run、跑迁移作业；不能改 IAM 与密钥
# （官网存储桶的写权限与刷 CDN 的权限在各环境里单独给，见 modules/platform/edge.tf）
resource "google_service_account" "deployer" {
  account_id   = "jl-deployer"
  display_name = "joblander CI 发布"
}

resource "google_project_iam_member" "deployer" {
  for_each = {
    for pair in setproduct(var.deploy_projects, ["roles/run.developer", "roles/iam.serviceAccountUser"]) :
    "${pair[0]}-${pair[1]}" => { project = pair[0], role = pair[1] }
  }
  project = each.value.project
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

# 从本机手动发起构建（gcloud builds submit）时源码先传到这个桶，构建用发布身份去读。
# 名字是 gcloud 的默认约定（<项目>_cloudbuild），不用另外指定；只给发布身份读这一个桶——
# 同项目里的状态桶存着生成的数据库密码，不能给项目级的读权限。
resource "google_storage_bucket" "build_sources" {
  name                        = "${var.project_id}_cloudbuild"
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "deployer_sources" {
  bucket = google_storage_bucket.build_sources.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

# 构建在本项目里跑，日志写在这里
resource "google_project_iam_member" "deployer_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

output "state_bucket" {
  value = google_storage_bucket.tf_state.name
}

output "deployer" {
  value = google_service_account.deployer.email
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
