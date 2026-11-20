"""复权与收益口径（FR-B-03 / ADR-004）。

关键约束：
- 净值收益一律用连续价（原始价 × adj_factor），停牌日 ffill → 当日收益 0；
- 分红不另计现金，否则与复权因子重复计入（TC-B-03）；
- 简单收益用于净值与业绩，对数收益仅用于 IC 统计，两者不得混用（REQUIREMENTS §8）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.market.calendar import ANN_VOL


def ffilled(adj: pd.DataFrame) -> pd.DataFrame:
    return adj.ffill()


def simple_returns(adj_close: pd.DataFrame) -> pd.DataFrame:
    f = ffilled(adj_close)
    return f.pct_change(fill_method=None).fillna(0.0)


def log_returns(adj_close: pd.DataFrame) -> pd.DataFrame:
    f = ffilled(adj_close)
    return np.log(f).diff()


def annualize(total: float, n_days: int) -> float:
    if n_days <= 0 or pd.isna(total):
        return float("nan")
    return (1.0 + float(total)) ** (ANN_VOL / n_days) - 1.0


def annual_vol(rets: pd.Series) -> float:
    if len(rets) < 2:
        return float("nan")
    return float(rets.std(ddof=1) * np.sqrt(ANN_VOL))


def factor_scale_check(adj_factor: pd.Series) -> float:
    """因子序列必须单调不减（除权只会推高后复权因子）。返回回退次数。"""
    d = adj_factor.diff().dropna()
    return int((d < -1e-9).sum())
