#!/usr/bin/env bash
# 生产灰度转正或回滚：promote.sh <项目> <区域> <回滚：0|1>
# 转正：五个服务的流量全部切到最新版本，并把它记成「稳定版本」；回滚：流量全部切回上一个稳定版本。
set -euo pipefail
project="$1"; region="$2"; rollback="${3:-0}"
for s in gateway meter engine worker sandbox; do
  svc="jl-prod-$s"
  if [ "$rollback" = "1" ]; then
    prev=$(gcloud run services describe "$svc" --project "$project" --region "$region" \
           --format='value(metadata.annotations."joblander/stable-revision")')
    gcloud run services update-traffic "$svc" --project "$project" --region "$region" --to-revisions "$prev=100"
  else
    gcloud run services update-traffic "$svc" --project "$project" --region "$region" --to-latest
    latest=$(gcloud run services describe "$svc" --project "$project" --region "$region" \
             --format='value(status.latestReadyRevisionName)')
    gcloud run services update "$svc" --project "$project" --region "$region" \
      --update-annotations "joblander/stable-revision=$latest" >/dev/null
  fi
done
