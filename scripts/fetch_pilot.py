#!/usr/bin/env python3
"""小样本导入（几分钟级），用于快速验证链路而不必先跑 30 分钟全量。

覆盖特殊案例：主板/创业板/科创板/北交所、退市标的、ST、高分红标的。
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.datasource.eastmoney import EastmoneyClient  # noqa: E402
from core.jobs.fetch import (open_store, run_quality, sync_bars,  # noqa: E402
                             sync_calendar, sync_index, sync_meta)

PILOT = ["600519.SH", "000001.SZ", "300750.SZ", "688981.SH", "601398.SH", "002415.SZ",
         "600028.SH", "000651.SZ", "601088.SH", "002594.SZ", "688116.SH", "300059.SZ",
         "600001.SH", "430047.BJ", "000005.SZ", "600595.SH", "002393.SZ", "600771.SH"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-04")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "pilot.duckdb"))
    a = ap.parse_args()
    s, e = date.fromisoformat(a.start), date.fromisoformat(a.end)
    store = open_store(a.db)
    client = EastmoneyClient(rate=5)
    out = {"instruments": sync_meta(store, client),
           "calendar": sync_calendar(store, client, s, e),
           "index_rows": sync_index(store, client, s, e)}
    out["bars"] = sync_bars(store, client, PILOT, s, e, batch=4)
    out["quality"] = run_quality(store, s, e, min_coverage=5)
    out["data_version"] = store.data_version(s, e)
    client.close()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
