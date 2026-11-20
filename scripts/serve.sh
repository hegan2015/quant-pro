#!/usr/bin/env bash
# 启动 API(8102) + 控制台(8101)。令牌在 ~/.config/quant-pro/auth.json（600）。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
if [ ! -x .venv/bin/python ]; then bash scripts/start.sh; fi
.venv/bin/python -c "from app.api.auth import ensure_dev_token; print('dev token 已就绪:', ensure_dev_token()[:12] + '…（完整值见 ~/.config/quant-pro/auth.json）')"
nohup .venv/bin/python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8102 \
  > data/logs/api.log 2>&1 &
echo $! > data/logs/api.pid
nohup .venv/bin/python scripts/serve_console.py > data/logs/console.log 2>&1 &
echo $! > data/logs/console.pid
sleep 2
curl -s http://127.0.0.1:8102/healthz
echo
echo "控制台 http://127.0.0.1:8101  （登录令牌见 ~/.config/quant-pro/auth.json）"
