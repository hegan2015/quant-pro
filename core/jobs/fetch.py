"""抓取作业：主数据 / 日历 / 指数 / 日线（FR-D-02/03/04、FR-O-01/02/03）。

幂等与续传：写入走 upsert；已入库标的默认跳过，重试只补缺口（FR-O-03）。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime

import pandas as pd

from core.datasource.eastmoney import EastmoneyClient, fetch_many
from core.data import quality
from core.market.calendar import build_calendar
from core.market.universe import instruments_from_list
from core.store.duckdb_store import DuckDBStore

DEFAULT_DB = "data/mkt.duckdb"
INDEX_CODES = ("000300", "000905", "000852", "000001", "399006")


def open_store(path: str | None = None) -> DuckDBStore:
    import os
    return DuckDBStore(path or os.path.join(os.getcwd(), DEFAULT_DB))


def sync_meta(store: DuckDBStore, client: EastmoneyClient) -> int:
    lst = client.stock_list()
    if lst.empty:
        raise RuntimeError("标的清单为空，拒绝继续（否则会以空清单覆盖 universe 口径）")
    inst = instruments_from_list(lst)
    return store.upsert_instruments(inst)


def sync_calendar(store: DuckDBStore, client: EastmoneyClient,
                  start: date, end: date) -> int:
    days = build_calendar(client, start, end)
    return store.upsert_calendar(days)


def sync_index(store: DuckDBStore, client: EastmoneyClient, start: date, end: date,
               codes: tuple[str, ...] = INDEX_CODES) -> int:
    rows = 0
    for code in codes:
        df = client.index_bars(code, start, end)
        rows += store.upsert_index_bars(df)
    return rows


def already_fetched(store: DuckDBStore, start: date, end: date) -> set[str]:
    rows = store.query(
        "SELECT DISTINCT symbol FROM daily_bar WHERE ts BETWEEN ? AND ?", [start, end])
    return {r[0] for r in rows}


def sync_bars(store: DuckDBStore, client: EastmoneyClient, symbols: list[str],
              start: date, end: date, batch: int = 100, resume: bool = True,
              progress: bool = True) -> dict:
    todo = [s for s in symbols if not resume or s not in already_fetched(store, start, end)]
    done, failed, rows = len(symbols) - len(todo), [], 0
    t0 = time.monotonic()
    store.job_start("fetch_bars_window", end, 1, f"fetch_bars_window|{start}|{end}")
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        df = fetch_many(client, chunk, start, end)
        if df.empty:
            failed.extend(chunk)
        else:
            got = set(df["symbol"].unique())
            failed.extend([s for s in chunk if s not in got])
            rows += store.upsert_bars(df)
        done += len(chunk)
        if progress:
            el = time.monotonic() - t0
            rate = done / el if el else 0
            eta = (len(todo) - done) / rate if rate else 0
            print(f"  [{done}/{len(symbols)}] rows={rows:,} 无数据={len(failed)} "
                  f"{rate:.1f} 只/秒 ETA={eta / 60:.1f} 分", flush=True)
    status = "SUCCESS" if not failed else "PARTIAL"
    store.job_finish("fetch_bars_window", end, 1, status, rows,
                     json.dumps({"no_data": len(failed)}) if failed else None)
    return {"rows": rows, "symbols_done": done, "no_data": failed,
            "elapsed_min": round((time.monotonic() - t0) / 60, 2), "status": status}


def run_quality(store: DuckDBStore, start: date, end: date,
                calendar: list[date] | None = None, min_coverage: int = 100) -> dict:
    """入库后校验（FR-D-07）：异常写 data_issue，阻断项供下游跳过。"""
    bars = store.query_df(
        "SELECT ts, symbol, open, high, low, close, pre_close, volume, amount, adj_factor,"
        " limit_up, limit_down, is_suspended, is_final FROM daily_bar"
        " WHERE ts BETWEEN ? AND ?", [start, end])
    bars["ts"] = pd.to_datetime(bars["ts"]).dt.date
    days = calendar or store.trade_days(start, end)
    expected = len(store.universe(end))
    issues = quality.check_bars(bars, days, expected, min_coverage=min_coverage)
    kinds = sorted(set(issues["kind"])) if not issues.empty else []
    cleared = store.clear_auto_issues(start, end, kinds + list(quality.AUTO_KINDS))
    n = store.write_issues(issues)
    return {"issues": n, "cleared_previous": cleared, **quality.summarize(issues)}


def bootstrap(start: date, end: date, db_path: str | None = None,
              universe: list[str] | None = None, rate: float = 5.0) -> dict:
    """一条命令完成：schema → 主数据 → 日历 → 指数 → 日线 → 质量校验。"""
    t0 = datetime.now()
    store = open_store(db_path)
    client = EastmoneyClient(rate=rate)
    out: dict = {"started_at": t0.isoformat()}
    out["instruments"] = sync_meta(store, client)
    days = build_calendar(client, start, end)
    out["calendar_days"] = store.upsert_calendar(days)
    out["index_rows"] = sync_index(store, client, start, end)
    symbols = universe or sorted(store.universe(end)["symbol"])
    out["universe"] = len(symbols)
    out["bars"] = sync_bars(store, client, symbols, start, end)
    out["quality"] = run_quality(store, start, end, days)
    out["data_version"] = store.data_version(start, end)
    out["elapsed_min"] = round((datetime.now() - t0).total_seconds() / 60, 2)
    client.close()
    return out
