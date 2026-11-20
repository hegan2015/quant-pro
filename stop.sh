#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
[ -f logs/api.pid ] && kill "$(cat logs/api.pid)" 2>/dev/null || true
rm -f logs/api.pid
PIDS=$(lsof -nP -iTCP:8102 -sTCP:LISTEN -t 2>/dev/null || true)
[ -n "$PIDS" ] && kill $PIDS 2>/dev/null || true
echo "quant-pro 已停止"
