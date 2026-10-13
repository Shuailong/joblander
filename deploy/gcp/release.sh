#!/usr/bin/env bash
# 发布到一个环境：release.sh <项目> <名字前缀> <引擎镜像> <网关镜像> <新版本流量百分比>
# 1) 用新镜像跑数据库迁移作业（只做向后兼容的变更，新旧版本可同时运行）
# 2) 五个服务各出一个新 revision；百分比 < 100 时先不接流量，再按比例切（灰度）
set -euo pipefail
project="$1"; prefix="$2"; engine="$3"; gateway="$4"; pct="${5:-100}"
region="${REGION:-asia-southeast1}"

gcloud run jobs update "${prefix}-migrate" --image "$engine" --project "$project" --region "$region" --quiet
gcloud run jobs execute "${prefix}-migrate" --wait --project "$project" --region "$region"
# 其余作业也换上新镜像：切流导入（引擎）、网关库复制与管理命令（网关）
gcloud run jobs update "${prefix}-cutover" --image "$engine" --project "$project" --region "$region" --quiet
for j in gw-cutover gw-cli; do
  gcloud run jobs update "${prefix}-$j" --image "$gateway" --project "$project" --region "$region" --quiet
done

deploy() {  # 服务 镜像
  local svc="${prefix}-$1" image="$2"
  if [ "$pct" = "100" ]; then
    gcloud run deploy "$svc" --image "$image" --project "$project" --region "$region" --quiet
  else
    gcloud run deploy "$svc" --image "$image" --project "$project" --region "$region" --no-traffic --quiet
    latest=$(gcloud run services describe "$svc" --project "$project" --region "$region" \
             --format='value(status.latestCreatedRevisionName)')
    gcloud run services update-traffic "$svc" --project "$project" --region "$region" \
      --to-revisions "${latest}=${pct}" --quiet
  fi
}

# 先下游后上游：新引擎能接旧网关的请求（账户令牌格式不变），反之亦然
deploy sandbox "$engine"
deploy meter "$gateway"
deploy worker "$engine"
deploy engine "$engine"
deploy gateway "$gateway"
