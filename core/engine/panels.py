"""价格面板：把长表行情转成 (ts × symbol) 宽表面板，供撮合与因子复用。

内存纪律：全 A × 10 年约 730 万行，宽表用 float32；universe 可裁剪为流动性前列，
避免一次性铺开 5000 列（P1 验证默认流动性前 1000，ALL_A 需显式指定）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from core.market.adjust import simple_returns  # noqa: F401

FIELDS = ["open", "high", "low", "close", "volume", "amount", "limit_up", "limit_down"]


@dataclass
class Panels:
    days: list[date]
    symbols: list[str]
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    amount: pd.DataFrame
    limit_up: pd.DataFrame
    limit_down: pd.DataFrame
    adj_close: pd.DataFrame
    float_share: pd.DataFrame
    r_adj: pd.DataFrame
    prev_close: pd.DataFrame

    @property
    def suspended(self) -> pd.DataFrame:
        return self.close.isna() | (self.volume.fillna(0) <= 0)

    def row(self, ts: date) -> dict[str, pd.Series]:
        """某日截面（返回副本，避免调用方改写面板）。"""
        return {k: getattr(self, k).loc[ts].copy() for k in
                ("open", "high", "low", "close", "volume", "amount",
                 "limit_up", "limit_down", "adj_close", "float_share")}

    def memory_mb(self) -> float:
        return float(round(sum(p.memory_usage(deep=False).sum() for p in
                         [self.open, self.high, self.low, self.close, self.volume,
                          self.amount, self.limit_up, self.limit_down, self.adj_close,
                          self.float_share, self.r_adj, self.prev_close]
                         ) / 1e6, 1))


def load(store, start: date, end: date, symbols: list[str] | None = None,
         max_symbols: int | None = None) -> Panels:
    """加载面板。symbols=None 时取区间内出现过行情的全部标的。"""
    if symbols is None:
        rows = store.query(
            "SELECT symbol, count(*) n FROM daily_bar WHERE ts BETWEEN ? AND ? GROUP BY symbol",
            [start, end])
        symbols = sorted(s for s, n in rows if n >= 60)
    if max_symbols:
        symbols = symbols[:max_symbols]
    raw = {f: store.pivot(start, end, f, symbols) for f in FIELDS}
    adj_close = store.pivot(start, end, "adj_close", symbols)
    float_share = store.pivot(start, end, "float_share", symbols)
    # 精度纪律：价格类必须 float64（分级误差会污染账本与整手判定），量/额/股本用 float32
    for df in (raw["open"], raw["high"], raw["low"], raw["close"],
               raw["limit_up"], raw["limit_down"], adj_close):
        for c in df.columns:
            df[c] = df[c].astype("float64")
    for df in (raw["volume"], raw["amount"], float_share):
        for c in df.columns:
            df[c] = df[c].astype("float32")
    days = list(adj_close.index)
    r_adj = simple_returns(adj_close)
    return Panels(
        days=days, symbols=list(adj_close.columns),
        open=raw["open"], high=raw["high"], low=raw["low"], close=raw["close"],
        volume=raw["volume"], amount=raw["amount"],
        limit_up=raw["limit_up"], limit_down=raw["limit_down"],
        adj_close=adj_close, float_share=float_share,
        r_adj=r_adj.reindex(days).astype("float64"),
        prev_close=raw["close"].shift(1),
    )


def liquid_universe(panels: Panels, as_of: date, top_n: int = 1000,
                    lookback: int = 20) -> list[str]:
    """按 20 日均成交额选流动性前列（PIT：只用 as_of 及之前）。"""
    idx = [d for d in panels.days if d <= as_of][-lookback:]
    amt = panels.amount.loc[idx].mean()
    return (amt.sort_values(ascending=False, kind="mergesort")
            .head(top_n).index.tolist())


def mcap_universe(panels: Panels, as_of: date, top_n: int = 1000) -> list[str]:
    idx = max([d for d in panels.days if d <= as_of])
    cap = (panels.close.loc[idx] * panels.float_share.loc[idx]).dropna()
    return (cap.sort_values(ascending=False, kind="mergesort")
            .head(top_n).index.tolist())


def mcap_of(panels: Panels, ts: date) -> pd.Series:
    return (panels.close.loc[ts] * panels.float_share.loc[ts]).astype("float64")


def nan_check(panels: Panels) -> dict:
    return {
        "days": len(panels.days), "symbols": len(panels.symbols),
        "close_nan_pct": round(float(panels.close.isna().mean().mean()) * 100, 3),
        "adj_nan_pct": round(float(panels.adj_close.isna().mean().mean()) * 100, 3),
        "memory_mb": panels.memory_mb(),
        "r_adj_nonfinite": int((~np.isfinite(panels.r_adj.to_numpy())).sum()),
    }
