terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source                = "hashicorp/google"
      version               = "~> 6.10"
      configuration_aliases = [google.billing] # 预算 API 不收个人登录凭据，除非请求里指明计费项目
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
