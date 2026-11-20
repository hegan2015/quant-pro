#!/usr/bin/env bash
# P1 一键验收。退出码 0 = 通过。
#   bash scripts/verify.sh            全量（含成本敏感性，较慢）
#   bash scripts/verify.sh --fast     跳过敏感性
#   bash scripts/verify.sh --only unit,selftest
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python scripts/accept.py "$@"
