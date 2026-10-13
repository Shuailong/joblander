#!/bin/sh
# GCP Cloud Run 入口：同一个镜像按 JOBLANDER_ROLE 跑成不同服务（见 joblander/cloud/__init__.py）。
# 没设 JOBLANDER_ROLE 时走 Fly 版原来的入口（entrypoint.sh），两种部署共用一个镜像。
set -e
PORT="${PORT:-8080}"
case "${JOBLANDER_ROLE:-}" in
  engine)  exec uvicorn --factory joblander.cloud.engine:create_engine_app  --host 0.0.0.0 --port "$PORT" --no-access-log ;;
  worker)  exec uvicorn --factory joblander.cloud.worker:create_worker_app  --host 0.0.0.0 --port "$PORT" --no-access-log ;;
  sandbox) exec uvicorn --factory joblander.cloud.sandbox:create_sandbox_app --host 0.0.0.0 --port "$PORT" --no-access-log ;;
  migrate) exec python -m joblander.cloud.migrate_db ;;
  cutover) exec python -m joblander.cloud.cutover "$@" ;;     # 切流：Fly 卷导入账户（参数由作业执行时给）
  "")      exec entrypoint.sh ;;
  *)       echo "unknown JOBLANDER_ROLE: $JOBLANDER_ROLE" >&2; exit 2 ;;
esac
