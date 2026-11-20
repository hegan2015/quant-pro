"""截面标准化（FR-F-03）：唯一实现，策略内不得自行标准化。"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_CROSS_SECTION = 100


def winsorize(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    return df.clip(lower=df.quantile(lower, axis=1), upper=df.quantile(upper, axis=1), axis=0)


def zscore(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1, ddof=1)
    sd = sd.replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def standardize(raw: pd.DataFrame, direction: int, min_n: int = MIN_CROSS_SECTION
                ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (标准化因子, 覆盖率诊断)。截面样本不足的日子不产出（FR-F-04）。"""
    n = raw.notna().sum(axis=1)
    ok = n >= min_n
    out = winsorize(raw.where(ok))
    out = zscore(out) * float(direction)
    diag = pd.DataFrame({"n": n, "coverage_ok": ok})
    return out.dropna(how="all"), diag
