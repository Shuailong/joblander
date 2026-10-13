output "load_balancer_ip" {
  description = "负载均衡器的公网 IP：app 与官网的 A 记录都指向它"
  value       = google_compute_global_address.lb.address
}

output "nat_egress_ip" {
  description = "所有服务出网的固定 IP（需要加白名单的外部服务用它）"
  value       = google_compute_address.nat.address
}

output "run_urls" {
  description = "各 Cloud Run 服务的确定性网址"
  value       = local.run_url
}

output "sql_private_ip" {
  value = google_sql_database_instance.main.private_ip_address
}

output "buckets" {
  value = {
    tenant_blobs = google_storage_bucket.tenant_blobs.name
    site         = google_storage_bucket.site.name
    migration    = google_storage_bucket.migration.name
  }
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "secrets_to_fill" {
  description = "需要手动放入值的外部密钥（gcloud secrets versions add …）"
  value       = [for n in local.external_secrets : google_secret_manager_secret.s[n].secret_id]
}

output "dns_name_servers" {
  description = "manage_dns=true 时，把 GoDaddy 的 NS 改成这几个"
  value       = var.manage_dns ? google_dns_managed_zone.site[0].name_servers : []
}

output "tasks_queue" {
  value = google_cloud_tasks_queue.jobs.id
}

output "dns_for_registrar" {
  description = "证书的 DNS 授权记录（manage_dns = true 时已自动加进 Cloud DNS，否则手工加到 GoDaddy）与当前流量指向"
  value = {
    acme_challenges = { for h, a in google_certificate_manager_dns_authorization.front : h => a.dns_resource_record[0] }
    serve_from      = var.serve_from
  }
}
