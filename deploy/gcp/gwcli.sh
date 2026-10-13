#!/usr/bin/env bash
# GCP 上的网关管理命令（与 Fly 上 `python -m gw.cli …` 同一套），跑完把输出打出来。
#   deploy/gcp/gwcli.sh invite a@x.com b@y.com
#   ENV=staging deploy/gcp/gwcli.sh users
# 命令跑在 Cloud Run 作业 jl-<环境>-gw-cli 里（连得上私有 IP 的网关库）；输出在 Cloud Logging，这里取回来。
set -euo pipefail
env="${ENV:-prod}"; project="${PROJECT:-joblander-$env}"; region="${REGION:-asia-southeast1}"
flags=()
[ $# -eq 0 ] || flags=(--args="^|^$(IFS='|'; echo "$*")")   # 自定义分隔符：参数里可以有逗号；不带参数 = 打印命令列表
ex=$(gcloud run jobs execute "jl-$env-gw-cli" --project "$project" --region "$region" --wait \
       ${flags[@]+"${flags[@]}"} --format='value(metadata.name)')
for _ in 1 2 3 4 5 6; do                                     # 日志入库有几秒延迟
  out=$(gcloud logging read "resource.type=cloud_run_job AND labels.\"run.googleapis.com/execution_name\"=\"$ex\"" \
          --project "$project" --order asc --freshness 1h --format='value(textPayload)')
  [ -n "$out" ] && { printf '%s\n' "$out"; exit 0; }
  sleep 5
done
echo "（$ex 跑完了，但还没取到输出；稍后在 Cloud Logging 里按 execution_name=$ex 查）" >&2
