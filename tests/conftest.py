"""测试夹具：手工构造的小样本面板（FIXTURE_MINI 等价），不依赖网络与数据库。"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core.engine.panels import Panels
from core.market.adjust import simple_returns


def build_panels(days: list[date], symbols: list[str], raw: dict[str, dict],
                 adj: dict[str, dict] | None = None) -> Panels:
    """raw/adj: symbol → {open/high/low/close/volume/amount/limit_up/limit_down/float_share}"""
    idx = pd.Index(days, name="ts")
    cols = symbols

    def frame(key, fill=np.nan, scale=1.0) -> pd.DataFrame:
        data = {s: [raw[s].get(key, [fill] * len(days))[i] if key in raw[s] else fill
                    for i in range(len(days))] for s in cols}
        return pd.DataFrame(data, index=idx).astype("float64") * scale

    close = frame("close")
    adj_close = pd.DataFrame(
        {s: (adj[s]["close"] if adj and s in adj else close[s].to_numpy()) for s in cols},
        index=idx).astype("float64")
    return Panels(
        days=days, symbols=cols,
        open=frame("open"), high=frame("high"), low=frame("low"), close=close,
        volume=frame("volume", fill=0.0), amount=frame("amount", fill=0.0),
        limit_up=frame("limit_up"), limit_down=frame("limit_down"),
        adj_close=adj_close, float_share=frame("float_share", fill=1e9),
        r_adj=simple_returns(adj_close),
        prev_close=close.shift(1),
    )


def days_of(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def mini_days() -> list[date]:
    return days_of(6)


@pytest.fixture
def mini_panels(mini_days) -> Panels:
    """6 日 × 4 标的，含一字涨停、停牌、除权三种特殊日。"""
    syms = ["AAA.SZ", "BBB.SZ", "CCC.SH", "DDD.SH"]
    raw = {
        # 第 3 日一字涨停（high=low=limit_up），买不进
        "AAA.SZ": {"open": [10, 11, 12.10, 12, 13, 13], "high": [10.5, 11.5, 12.10, 12.5, 13.5, 13.5],
                   "low": [9.8, 10.8, 12.10, 11.5, 12.5, 12.6], "close": [10, 11, 12.10, 12, 13, 13],
                   "volume": [1e6] * 6, "amount": [1.2e7] * 6,
                   "limit_up": [11, 12.1, 13.31, 13.2, 14.3, 14.3],
                   "limit_down": [9, 9.9, 10.89, 10.8, 11.7, 11.7]},
        # 第 4 日停牌（无行情）
        "BBB.SZ": {"open": [20, 21, 22, np.nan, 23, 24], "high": [21, 22, 23, np.nan, 24, 25],
                   "low": [19, 20, 21, np.nan, 22, 23], "close": [20, 21, 22, np.nan, 23, 24],
                   "volume": [5e5, 5e5, 5e5, 0, 5e5, 5e5], "amount": [1e7] * 6,
                   "limit_up": [22, 23.1, 24.2, np.nan, 25.3, 26.4],
                   "limit_down": [18, 18.9, 19.8, np.nan, 20.7, 21.6]},
        # 第 5 日除权：真实价 -10%，分红 2 元/股 → 连续价持平
        "CCC.SH": {"open": [30, 31, 32, 33, 29.7, 30], "high": [31, 32, 33, 34, 30, 31],
                   "low": [29, 30, 31, 32, 29.5, 29.5], "close": [30, 31, 32, 33, 29.7, 30],
                   "volume": [8e5] * 6, "amount": [2.4e7] * 6,
                   "limit_up": [33, 34.1, 35.2, 36.3, 36.3, 32.67],
                   "limit_down": [27, 27.9, 28.8, 29.7, 26.73, 26.73]},
        "DDD.SH": {"open": [5, 5.1, 5.2, 5.3, 5.4, 5.5], "high": [5.2, 5.3, 5.4, 5.5, 5.6, 5.7],
                   "low": [4.8, 4.9, 5.0, 5.1, 5.2, 5.3], "close": [5, 5.1, 5.2, 5.3, 5.4, 5.5],
                   "volume": [2e6] * 6, "amount": [1.05e7] * 6,
                   "limit_up": [5.5, 5.61, 5.72, 5.83, 5.94, 6.05],
                   "limit_down": [4.5, 4.59, 4.68, 4.77, 4.86, 4.95]},
    }
    adj = {"CCC.SH": {"close": [30, 31, 32, 33, 33.0, 33.3]}}
    p = build_panels(mini_days, syms, raw, adj)
    p.limit_up.loc[mini_days[2], "AAA.SZ"] = 12.10
    p.limit_down.loc[mini_days[2], "AAA.SZ"] = 10.89
    return p
