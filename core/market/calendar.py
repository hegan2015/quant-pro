"""交易日历（AP-01：日历口径集中在此）。"""
from __future__ import annotations

from datetime import date

from core.datasource.eastmoney import EastmoneyClient, DataSourceUnavailable

CALENDAR_INDEX = "000001"          # 上证指数：日线覆盖全部交易日
ANN_VOL = 252                      # 年化交易日
LOT = 100                          # A 股一手
NEW_LISTING_MIN_DAYS = 60          # 次新过滤（交易日近似）


class CalendarError(RuntimeError):
    """QUANT-D-001 交易日历缺失。"""


def build_calendar(client: EastmoneyClient, start: date, end: date) -> list[date]:
    """日历来自指数日线；抓取失败必须抛错，不得静默返回空（FR-D-06）。"""
    try:
        days = client.list_dates(CALENDAR_INDEX, start, end)
    except DataSourceUnavailable as exc:
        raise CalendarError(f"交易日历不可得：{exc}") from exc
    if not days:
        raise CalendarError(f"交易日历区间 {start}..{end} 为空")
    return days
