"""可交易性与交易单位（FR-B-04/05/07/08）。"""
from __future__ import annotations

from datetime import date

import pandas as pd

from core.market.calendar import LOT, NEW_LISTING_MIN_DAYS

REASON_CN = {
    "SUSPENDED": "停牌无法成交",
    "NOT_FINAL": "行情未收盘终态",
    "LIMIT_UP_ONE_PU": "一字涨停无法买入",
    "LIMIT_DOWN_ONE_PU": "一字跌停无法卖出",
    "CASH_SHORT": "现金不足（整手后为 0）",
    "SELLABLE_SHORT": "T+1 当日买入不可卖",
    "RISK_REJECT": "风控拒绝",
    "DELISTED": "退市进入清算",
    "SKIPPED_TURNOVER": "换手上限裁剪",
    "NEW_LISTING": "上市不足 60 交易日",
    "ST_BANNED": "ST 标的禁止买入",
    "BLACKLIST": "黑名单",
    "NO_BAR": "无行情记录",
    "LOT_TOO_LARGE": "目标金额不足一手，无法建仓",
}


def tradable(side: str, bar: pd.Series | None, *, list_date: date | None = None,
             trade_date: date | None = None, is_st: bool = False,
             in_blacklist: bool = False,
             min_age_days: int = NEW_LISTING_MIN_DAYS) -> str | None:
    """返回拒单码或 None。side ∈ {BUY, SELL}。"""
    if bar is None:
        return "NO_BAR"
    if pd.isna(bar.get("close")) or bool(bar.get("is_suspended", False)):
        return "SUSPENDED"
    if not bool(bar.get("is_final", True)):
        return "NOT_FINAL"
    if in_blacklist:
        return "BLACKLIST"
    if side == "BUY":
        if is_st:
            return "ST_BANNED"
        if min_age_days and list_date and trade_date and \
                trade_age_days(list_date, trade_date) < min_age_days:
            return "NEW_LISTING"
        if _one_pu(bar, up=True):
            return "LIMIT_UP_ONE_PU"
    elif _one_pu(bar, up=False):
        return "LIMIT_DOWN_ONE_PU"
    return None


def _one_pu(bar: pd.Series, up: bool) -> bool:
    """一字板：最高=最低且等于涨/跌停价（用开盘价判定可成交性）。"""
    hi, lo = bar.get("high"), bar.get("low")
    if hi is None or lo is None or pd.isna(hi) or pd.isna(lo) or abs(hi - lo) > 1e-9:
        return False
    limit = bar.get("limit_up") if up else bar.get("limit_down")
    if limit is None or pd.isna(limit):
        return False
    return abs(bar.get("open") - limit) < 0.005


def trade_age_days(list_date, trade_date: date) -> int:
    """自然日→交易日近似（周末折算），用于次新过滤。"""
    if hasattr(list_date, "date") and not isinstance(list_date, date):
        list_date = list_date.date()
    return max(0, (trade_date - list_date).days * 5 // 7)


def floor_lot(qty: float) -> int:
    """买入按整手向下取整（FR-B-04）。"""
    return int(qty // LOT) * LOT


def sell_qty(position_qty: int, want: int) -> int:
    """卖出允许零股一次性卖光。"""
    return int(min(max(want, 0), position_qty))
