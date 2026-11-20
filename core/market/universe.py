"""样本池构建与过滤（FR-D-01 / FR-S-05 前置）。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from core.market.tradability import trade_age_days


def instruments_from_list(list_df: pd.DataFrame, first_ts: dict[str, date] | None = None,
                          list_date_col: str | None = None) -> pd.DataFrame:
    """东财 clist → instrument 主数据。list_date 优先取接口字段，退化为窗口首条行情日。"""
    df = list_df.copy()
    df["is_st"] = df.get("is_st", pd.Series(False, index=df.index)).astype(bool)
    col = list_date_col or "list_date_raw"
    if col in df:
        df["list_date"] = pd.to_datetime(df[col].astype("Int64").astype("string"),
                                         format="%Y%m%d", errors="coerce").dt.date
    else:
        df["list_date"] = None
    if first_ts:
        fill = df["list_date"].isna()
        df.loc[fill, "list_date"] = df.loc[fill, "symbol"].map(first_ts)
    df["delist_date"] = None
    df["industry_l1"] = df.get("industry")
    df["industry_l1"] = df["industry_l1"].where(df["industry_l1"].ne("-"), None)
    df["total_share"] = None
    df["float_share"] = None
    keep = ["symbol", "name", "exchange", "board", "list_date", "delist_date",
            "is_st", "industry_l1", "total_share", "float_share"]
    for c in keep:
        if c not in df:
            df[c] = None
    return df[keep]


def tradable_universe(store, as_of: date, *, exclude_st: bool = True,
                      min_age_days: int = 60, boards: tuple[str, ...] = ("main", "gem", "star"),
                      min_bars_20: int = 1) -> list[str]:
    """按历史日期回溯在市标的，并剔除 ST / 次新 / 非目标板块 / 近 20 日无行情者。"""
    inst = store.universe(as_of)
    if inst.empty:
        return []
    if exclude_st:
        inst = inst[~inst["is_st"].fillna(False).astype(bool)]
    inst = inst[inst["board"].isin(boards)]
    if min_age_days:
        inst = inst[inst["list_date"].apply(
            lambda d: d is None or pd.isna(d) or trade_age_days(d, as_of) >= min_age_days)]
    recent = store.con.execute(
        """SELECT symbol, count(*) AS n FROM daily_bar
           WHERE ts <= ? AND ts >= ? GROUP BY symbol""",
        [as_of, pd.Timestamp(as_of) - pd.Timedelta(days=45)]).df()
    if not recent.empty:
        ok = set(recent[recent["n"] >= min_bars_20]["symbol"])
        inst = inst[inst["symbol"].isin(ok)]
    return sorted(inst["symbol"].tolist())
