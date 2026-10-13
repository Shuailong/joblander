# 网络：所有 Cloud Run 服务直连 VPC 出网，经 Cloud NAT 的固定 IP 访问外网；
# Cloud SQL 只有私有 IP；沙箱服务打上 jl-sandbox 标签，出网一律被防火墙拒绝。

resource "google_compute_network" "vpc" {
  name                    = "${local.name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "run" {
  name                     = "${local.name}-run"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_router" "nat" {
  name    = "${local.name}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_address" "nat" {
  name    = "${local.name}-nat-ip"
  project = var.project_id
  region  = var.region
}

resource "google_compute_router_nat" "nat" {
  name                               = "${local.name}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.run.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# 沙箱：跑用户代码的服务，出网全部拒绝（含 Google API 与元数据以外的一切地址）
resource "google_compute_firewall" "sandbox_no_egress" {
  name               = "${local.name}-sandbox-deny-egress"
  project            = var.project_id
  network            = google_compute_network.vpc.id
  direction          = "EGRESS"
  priority           = 100
  target_tags        = ["jl-sandbox"]
  destination_ranges = ["0.0.0.0/0"]
  deny {
    protocol = "all"
  }
}

# Cloud SQL 私有 IP：服务网络对等
resource "google_compute_global_address" "sql_peering" {
  name          = "${local.name}-sql-peering"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_peering.name]
}
