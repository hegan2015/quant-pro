#!/usr/bin/env bash
# quant-pro 一键启动：探测 Python 3.12 → venv → 依赖 → 自检 → 状态
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for c in "$HOME/.local/bin/python3.12" python3.12 /opt/homebrew/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[错误] 未找到 Python 3.12。系统 python3 为 $(python3 -V 2>&1)，akshare/pandas 生态要求 >=3.10。"
  echo "       安装：brew install python@3.12 或 uv python install 3.12"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "[1/3] 创建虚拟环境（$($PY -V)）"
  "$PY" -m venv .venv
fi
echo "[2/3] 安装依赖"
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q pandas numpy scipy duckdb pyarrow httpx typer pydantic pytest

echo "[3/3] 环境自检"
.venv/bin/python - <<'EOF'
import duckdb, pandas, numpy, sys
print(f"python {sys.version.split()[0]} | pandas {pandas.__version__} | "
      f"numpy {numpy.__version__} | duckdb {duckdb.__version__}（进程内，无需容器）")
EOF

if [ ! -f data/mkt.duckdb ]; then
  echo
  echo "尚无行情库。首次导入全 A 日线（约 40 分钟，可断点续传）："
  echo "  .venv/bin/python scripts/fetch_all.py"
  echo "或先跑小样本验证："
  echo "  .venv/bin/python scripts/fetch_pilot.py"
else
  .venv/bin/python -m app.cli.main status
fi
