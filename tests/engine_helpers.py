"""测试用策略（供 test_engine_core 与 test_lookahead 共用）。"""
from __future__ import annotations

from datetime import date

from core.strategy.base import AsOfView, Strategy, TargetPortfolio


class BuyAndHold(Strategy):
    strategy_id = "test_buy_hold"
    version = "v1"

    def __init__(self, weights=None):
        self.w = weights or {"AAA.SZ": 0.5, "BBB.SZ": 0.5}

    def rebalance_days(self, ctx, start, end):
        return [ctx.days[1]]

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        return TargetPortfolio(weights=dict(self.w))


class LeakStrategy(Strategy):
    """故意读取 T+1 收盘价选股：用于验证门禁能拦下前视偏差。"""

    strategy_id = "test_leak"
    version = "v1"

    def rebalance_days(self, ctx, start, end):
        return [ctx.days[1], ctx.days[3]]

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        nxt = view._ctx.panels.close.iloc[view._idx + 1]
        return TargetPortfolio(weights={s: 0.5 for s in
                                        nxt.sort_values(ascending=False).index[:1]})
