#!/bin/sh
# 首次启动：卷是空的，生成最小配置并搭好 workspace 骨架；之后每次启动原样复用。
# 真实的个人参数（报价锚点、红线词表、简历）由网页设置向导写入，不在这里。
set -e
CONFIG="${JOBLANDER_CONFIG:-/data/config.yaml}"
if [ ! -f "$CONFIG" ]; then
  mkdir -p "$(dirname "$CONFIG")"
  cat > "$CONFIG" <<YAML
workspace_dir: /data/workspace
llm:
  provider: openai
  model: ${JOBLANDER_MODEL:-gpt-5.6-sol}
  model_flash: ${JOBLANDER_MODEL_FLASH:-gpt-5.6-luna}
  model_eval: ${JOBLANDER_MODEL_EVAL:-gpt-5.6-sol}
sentinel:
  rules: []
YAML
fi
joblander onboard
exec joblander web --host "${JOBLANDER_HOST:-::}" --port "${PORT:-8899}"
