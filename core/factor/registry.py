"""因子注册表与内置因子（FR-F-01/02）。

P1 说明：默认免费源不含 PIT 财务数据（A-02 未接 tushare），因此内置因子全部
可由日线派生；估值/质量类因子在接入财务 PIT 后再注册，不用品前数据凑数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from core.engine.panels import Panels


@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    name: str
    direction: int
    deps: tuple[str, ...]
    fn: Callable[[Panels], pd.DataFrame]


def _mom(p: Panels, n: int) -> pd.DataFrame:
    return p.adj_close / p.adj_close.shift(n) - 1.0


def _vol(p: Panels, n: int) -> pd.DataFrame:
    return p.r_adj.rolling(n, min_periods=n).std() * np.sqrt(252.0)


def _turnover(p: Panels, n: int) -> pd.DataFrame:
    to = p.volume / p.float_share
    return to.rolling(n, min_periods=n).mean()


def _float_mcap(p: Panels) -> pd.DataFrame:
    cap = p.close * p.float_share
    return np.log(cap.where(cap > 0))


def _amihud(p: Panels, n: int) -> pd.DataFrame:
    ill = p.r_adj.abs() / p.amount.replace(0, np.nan)
    return ill.rolling(n, min_periods=n).mean() * 1e8


def _price_position(p: Panels, n: int) -> pd.DataFrame:
    """收盘价在滚动区间内的相对位置（0~1），替代需要财务数据的趋势质量类因子。"""
    hi = p.adj_close.rolling(n, min_periods=n).max()
    lo = p.adj_close.rolling(n, min_periods=n).min()
    return (p.adj_close - lo) / (hi - lo).replace(0, np.nan)


REGISTRY: dict[str, FactorSpec] = {}


def register(spec: FactorSpec) -> FactorSpec:
    REGISTRY[spec.factor_id] = spec
    return spec


for _n in (20, 60, 120):
    register(FactorSpec(f"mom_{_n}", f"动量 {_n} 日", 1, ("adj_close",),
                        lambda p, n=_n: _mom(p, n)))
register(FactorSpec("rev_5", "5 日反转", 1, ("adj_close",), lambda p: -_mom(p, 5)))
register(FactorSpec("vol_60", "60 日波动率", -1, ("r_adj",), lambda p: _vol(p, 60)))
register(FactorSpec("turnover_20", "20 日换手率", -1, ("volume", "float_share"),
                    lambda p: _turnover(p, 20)))
register(FactorSpec("size_float", "对数流通市值", -1, ("close", "float_share"), _float_mcap))
register(FactorSpec("amihud_20", "非流动性 20 日", 1, ("r_adj", "amount"),
                    lambda p: _amihud(p, 20)))
register(FactorSpec("pos_120", "120 日价格分位", 1, ("adj_close",),
                    lambda p: _price_position(p, 120)))


def compute(factor_id: str, panels: Panels) -> pd.DataFrame:
    if factor_id not in REGISTRY:
        raise KeyError(f"因子未注册：{factor_id}")
    return REGISTRY[factor_id].fn(panels)


def meta_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        "factor_id": s.factor_id, "name": s.name, "direction": s.direction,
        "deps": ",".join(s.deps), "enabled": True,
    } for s in REGISTRY.values()])
