#!/usr/bin/env python3
"""全 A 日线首次导入（FR-D-02）：主数据 → 日历 → 指数 → 日线 → 质量校验。

用法：python3 scripts/fetch_all.py [--start 2016-01-01] [--end 2025-12-31] [--rate 6]
已入库标的自动跳过（FR-O-03 断点续传），可反复执行直到 SUCCESS。
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.jobs.fetch import bootstrap  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--rate", type=float, default=6.0)
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "mkt.duckdb"))
    a = ap.parse_args()
    out = bootstrap(date.fromisoformat(a.start), date.fromisoformat(a.end),
                    db_path=a.db, rate=a.rate)
    print("导入结果：", out)
    return 0 if out["bars"]["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
