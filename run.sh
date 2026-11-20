#!/usr/bin/env bash
# quant-pro 启动：API + 控制台同源 :8102（ops 运维台入口）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
[ -x .venv/bin/python ] || { echo "先执行 bash scripts/start.sh"; exit 1; }
if lsof -nP -iTCP:8102 -sTCP:LISTEN >/dev/null 2>&1; then echo "已在运行：:8102"; exit 0; fi
nohup .venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8102 >> logs/api.log 2>&1 &
echo $! > logs/api.pid
for i in $(seq 1 40); do
  sleep 1
  if curl -sf http://127.0.0.1:8102/healthz >/dev/null 2>&1; then echo "quant-pro 就绪 http://127.0.0.1:8102"; exit 0; fi
done
echo "启动超时，见 logs/api.log"; exit 1
