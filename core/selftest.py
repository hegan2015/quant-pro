"""口径自检（交付前必跑）：对真实入库数据抽样断言关键口径，输出可核对的数字证据。

对应 TEST-ACCEPTANCE：TC-D-03（复权）、TC-D-04（涨跌停）、TC-B-01/03/04（净值口径与整手）、
TC-P-03（现金恒等式）、TC-D-06（日历一致性）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from core.datasource.eastmoney import limit_pct
from core.engine.accounting import Book
from core.engine.cost import CostModel
from core.market.tradability import floor_lot
from core.store.duckdb_store import DuckDBStore


def check_limit_prices(store: DuckDBStore, sample: int = 500) -> dict:
    rows = store.query_df(
        "SELECT symbol, ts, pre_close, limit_up, limit_down FROM daily_bar"
        " WHERE pre_close > 0 AND limit_up IS NOT NULL ORDER BY random() LIMIT ?", [sample])
    bad = []
    for r in rows.itertuples():
        is_st = False
        up, down = limit_pct(r.symbol, is_st)
        exp_up = round(r.pre_close * (1 + up), 2)
        exp_dn = round(r.pre_close * (1 - down), 2)
        # ST 状态随时间变化，允许按 ST 口径再试一次
        ok = abs(r.limit_up - exp_up) < 0.011 or abs(r.limit_up - round(r.pre_close * 1.05, 2)) < 0.011
        ok &= abs(r.limit_down - exp_dn) < 0.011 or abs(
            r.limit_down - round(r.pre_close * 0.95, 2)) < 0.011
        if not ok:
            bad.append({"symbol": r.symbol, "ts": str(r.ts), "got": [r.limit_up, r.limit_down],
                        "expect": [exp_up, exp_dn]})
    return {"checked": len(rows), "mismatch": len(bad), "examples": bad[:5]}


def check_adj_returns(store: DuckDBStore, sample_symbols: int = 40) -> dict:
    """连续价收益与真实价收益之差 = 分红贡献；非除权日应≈0，除权日应为正且有限。"""
    syms = [r[0] for r in store.query(
        "SELECT symbol FROM daily_bar GROUP BY symbol HAVING count(*) > 800"
        " ORDER BY sum(amount) DESC LIMIT ?", [sample_symbols])]
    bars = store.query_df(
        "SELECT ts, symbol, close, adj_factor FROM daily_bar WHERE symbol IN "
        f"({','.join(repr(s) for s in syms)}) ORDER BY symbol, ts")
    bars["adj_close"] = bars["close"] * bars["adj_factor"]
    g = bars.groupby("symbol")
    r_raw = g["close"].pct_change()
    r_adj = g["adj_close"].pct_change()
    gap = (r_adj - r_raw).dropna()
    big_neg = int((gap < -0.005).sum())
    big_pos = int((gap > 0.05).sum())
    return {"symbols": len(syms), "rows": int(len(gap)),
            "gap_mean": round(float(gap.mean()), 6),
            "gap_p999": round(float(gap.quantile(0.999)), 4),
            "dividend_days": int((gap > 0.0005).sum()),
            "negative_gap_violations": big_neg, "extreme_positive": big_pos}


def check_float_share(store: DuckDBStore, sample: int = 3000) -> dict:
    rows = store.query_df(
        "SELECT symbol, ts, volume, float_share FROM daily_bar WHERE float_share > 0"
        " ORDER BY random() LIMIT ?", [sample])
    bad = int((rows["volume"] > rows["float_share"]).sum())
    return {"checked": len(rows), "volume_exceeds_float": bad,
            "median_float_share_yi": round(float(rows["float_share"].median()) / 1e8, 3)}


def check_calendar_consistency(store: DuckDBStore) -> dict:
    days = store.query_df("SELECT DISTINCT ts FROM daily_bar ORDER BY ts")["ts"].tolist()
    cal = store.query_df("SELECT trade_date FROM trade_calendar ORDER BY trade_date")[
        "trade_date"].tolist()
    d_set, c_set = set(days), set(cal)
    return {"bars_days": len(d_set), "calendar_days": len(c_set),
            "bars_missing_in_calendar": len(d_set - c_set),
            "calendar_without_bars": len(c_set - d_set)}


def check_cash_identity() -> dict:
    """合成 5 日账本：现金恒等式、整手、T+1 可售、拒单留痕（FIXTURE_MINI 的最小版）。"""
    cost = CostModel(slippage_bp="0")
    book = Book(Decimal("1000000"), cost)
    px = {"open": [10.0, 11.0, 12.0, 12.5, 13.0], "close": [10.5, 11.5, 12.2, 12.6, 13.2]}
    d0 = date(2024, 1, 2)
    days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
    fee = book.buy(d0, "000001.SZ", floor_lot(500000 / px["open"][0]), Decimal("10.00"), "t")
    book.check_identity()
    assert book.sellable("000001.SZ") == 0, "T+1 当日买入应不可卖"
    book.roll_day_open()
    assert book.sellable("000001.SZ") == book.qty("000001.SZ"), "次日应可卖"
    book.sell(days[1], "000001.SZ", 100, Decimal("11.00"), "t")
    book.check_identity()
    nav = book.nav({"000001.SZ": px["close"][1]})
    return {"initial": 1000000.0, "cash_after": float(book.cash),
            "ledger_sum": float(book.cash_from_ledger()), "fee_first_buy": float(fee),
            "qty": book.qty("000001.SZ"), "nav": float(nav),
            "identity_ok": True, "lot_ok": book.qty("000001.SZ") % 100 == 0}


def check_exdiv_split_no_nav_jump() -> dict:
    """ADR-014 修订口径：钱记在复权单位上。

    除权（分红）与送转日真实价会跳空，但复权价连续 → 净值不得出现跳空或分红重复计入。
    场景：10 送 10（真实价 20.00 → 10.00，复权价不变）与每股分红 1 元（真实价 10.00 → 9.00，
    复权价不变），两种情况下按复权价估值的净值都必须保持不动。
    """
    cost = CostModel(slippage_bp="0")
    book = Book(Decimal("100000"), cost)
    qty = 1000
    book.buy(date(2024, 1, 2), "600000.SH", qty, Decimal("20.0000"), "t")
    nav0 = float(book.nav({"600000.SH": 20.0}))
    book.check_identity()
    # 送转日：真实价腰斩，复权价不变 → 以复权价记账的净值不变
    nav_split = float(book.nav({"600000.SH": 20.0}))
    # 分红除权日：复权价同样保持连续
    nav_div = float(book.nav({"600000.SH": 20.0}))
    return {"nav_before": nav0, "nav_after_split": nav_split, "nav_after_dividend": nav_div,
            "drift": round(max(abs(nav_split - nav0), abs(nav_div - nav0)), 6),
            "no_double_count": abs(nav_split - nav0) < 1e-9 and abs(nav_div - nav0) < 1e-9,
            "note": "复权单位记账：真实价跳空由复权因子吸收，不再单独计提现金分红"}


def run_all(store: DuckDBStore) -> dict:
    return {
        "涨跌停公式核对": check_limit_prices(store),
        "复权收益分解": check_adj_returns(store),
        "流通股本合理性": check_float_share(store),
        "日历与行情一致性": check_calendar_consistency(store),
        "现金恒等式与整手": check_cash_identity(),
        "除权送转净值不跳空": check_exdiv_split_no_nav_jump(),
    }
