#!/usr/bin/env bash
# P2 验收：内核用例 + API 门禁用例 + 控制台浏览器实测。
# 前置：bash scripts/serve.sh（API 8102 / 控制台 8101）
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest tests/test_p2.py tests/test_api.py -q
curl -sf http://127.0.0.1:8102/healthz > /dev/null || { echo "API 未启动，先跑 scripts/serve.sh"; exit 1; }
.venv/bin/python scripts/ui_smoke.py
