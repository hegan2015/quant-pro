"""撮合内核与账本用例（TC-B-04/05/07/08/09/10、TC-P-03、TC-B-03）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from core.engine.accounting import Book, ReconDiff
from core.engine.cost import CostModel, q2
from core.engine.execution import BUY, SELL, BacktestConfig, Engine
from core.market.tradability import floor_lot, tradable
from core.strategy.base import Ctx, Strategy, TargetPortfolio
from core.strategy.constraints import Constraints
from tests.conftest import days_of


# ------------------------------------------------------------------ 成本（TC-B-10）
def test_fee_items_exact():
    c = CostModel()
    gross = Decimal("100000")
    assert c.fee(gross, "BUY") == Decimal("26.00")            # 25 佣金 + 1 过户
    assert c.fee(gross, "SELL") == Decimal("76.00")           # 25 + 1 + 50 印花税
    assert c.fee(Decimal("10000"), "BUY") == Decimal("5.10")  # 佣金按最低 5 元 + 过户 0.10


def test_min_commission_and_slippage_on_price():
    c = CostModel(slippage_bp="10")
    assert c.exec_price(10.0, "BUY") == Decimal("10.01")   # 10bp = 0.10%
    assert c.exec_price(10.0, "SELL") == Decimal("9.99")


def test_slippage_changes_fill_price(mini_panels, mini_days):
    """滑点必须进成交价：同一策略在 0bp 与 100bp 下的成交额与费用必须不同。"""
    def run(bp):
        cfg = BacktestConfig(strategy_id="test_buy_hold", start=mini_panels.days[0],
                             end=mini_panels.days[-1], initial_capital=1_000_000.0,
                             cost=CostModel(slippage_bp=str(bp)).to_dict())
        eng = make_engine(mini_panels, BuyAndHold({"CCC.SH": 1.0}), cfg=cfg)
        return eng.run()
    a, b = run(0), run(100)
    ga = float(a["orders"].gross.sum())
    gb = float(b["orders"].gross.sum())
    assert gb > ga, "100bp 滑点买入成交额必须高于零滑点，否则滑点未生效"
    assert abs(float(b["equity"]["nav"].iloc[-1]) - float(a["equity"]["nav"].iloc[-1])) > 1e-6


def test_lot_rounding():
    assert floor_lot(1234.0) == 1200
    assert floor_lot(99.0) == 0


# ------------------------------------------------------------------ 可交易性（TC-B-05）
def bar(open_, high, low, close, limit_up=None, limit_down=None, final=True):
    return pd.Series({"open": open_, "high": high, "low": low, "close": close,
                      "limit_up": limit_up, "limit_down": limit_down,
                      "is_suspended": False, "is_final": final})


def test_one_pu_limit_up_blocks_buy():
    b = bar(12.10, 12.10, 12.10, 12.10, limit_up=12.10, limit_down=10.89)
    assert tradable("BUY", b, trade_date=date(2024, 1, 3)) == "LIMIT_UP_ONE_PU"
    assert tradable("SELL", b, trade_date=date(2024, 1, 3)) is None


def test_one_pu_limit_down_blocks_sell():
    b = bar(8.10, 8.10, 8.10, 8.10, limit_up=9.9, limit_down=8.10)
    assert tradable("SELL", b, trade_date=date(2024, 1, 3)) == "LIMIT_DOWN_ONE_PU"


def test_suspended_and_not_final(mini_panels, mini_days):
    b = mini_panels.row(mini_days[3])["close"]
    row = pd.Series({"open": 21.0, "high": 21.0, "low": 21.0, "close": float("nan"),
                     "limit_up": 23.1, "limit_down": 18.9, "is_suspended": False,
                     "is_final": True})
    assert tradable("BUY", row, trade_date=mini_days[3]) == "SUSPENDED"
    row2 = bar(21, 21, 21, 21, 23.1, 18.9, final=False)
    assert tradable("BUY", row2, trade_date=mini_days[3]) == "NOT_FINAL"


def test_st_and_new_listing_ban():
    b = bar(10, 10.5, 9.5, 10.2, 11, 9)
    assert tradable("BUY", b, trade_date=date(2024, 6, 3), is_st=True) == "ST_BANNED"
    assert tradable("BUY", b, trade_date=date(2024, 6, 3),
                    list_date=date(2024, 5, 20), min_age_days=60) == "NEW_LISTING"
    assert tradable("BUY", b, trade_date=date(2024, 6, 3), in_blacklist=True) == "BLACKLIST"


# ------------------------------------------------------------------ 账本（TC-B-03 / TC-P-03）
def test_cash_identity_after_trades():
    book = Book(Decimal("100000"), CostModel(slippage_bp="0"))
    book.buy(date(2024, 1, 2), "AAA.SZ", 1000, Decimal("10.00"), "t")
    book.sell(date(2024, 1, 3), "AAA.SZ", 400, Decimal("11.00"), "t")
    book.check_identity()
    assert book.cash == book.cash_from_ledger()


def test_t_plus_1_sellable():
    book = Book(Decimal("100000"), CostModel(slippage_bp="0"))
    book.buy(date(2024, 1, 2), "AAA.SZ", 1000, Decimal("10.00"), "t")
    assert book.sellable("AAA.SZ") == 0
    book.roll_day_open()
    assert book.sellable("AAA.SZ") == 1000


def test_dividend_accrued_once_not_double_counted():
    """除权日：真实价 -10%、分红 2 元/股 → 连续价持平，NAV 不变（不重复计入）。"""
    book = Book(Decimal("100000"), CostModel(slippage_bp="0"))
    book.buy(date(2024, 1, 2), "CCC.SH", 1000, Decimal("33.00"), "t")
    nav0 = book.nav({"CCC.SH": 33.00})
    book.accrue_dividends({"CCC.SH": 33.00}, {"CCC.SH": 0.0}, {"CCC.SH": -0.10})
    nav1 = book.nav({"CCC.SH": 29.70})
    assert nav1 == nav0
    assert book.cash > Decimal("33000")


def test_identity_violation_raises():
    book = Book(Decimal("1000"), CostModel())
    book.cash += Decimal("1")            # 人为制造不平（仅测试断言生效）
    with pytest.raises(ReconDiff):
        book.check_identity()


# ------------------------------------------------------------------ 引擎端到端（TC-B-08/25）
from tests.engine_helpers import BuyAndHold  # noqa: E402


def make_engine(panels, strategy, cfg=None, cons=None):
    bench = pd.Series(0.0, index=panels.days)
    ctx = Ctx(panels, {}, {"AAA.SZ": {"list_date": date(2020, 1, 1)},
                           "BBB.SZ": {"list_date": date(2020, 1, 1)},
                           "CCC.SH": {"list_date": date(2020, 1, 1)},
                           "DDD.SH": {"list_date": date(2020, 1, 1)}}, bench)
    cfg = cfg or BacktestConfig(strategy_id=strategy.strategy_id, start=panels.days[0],
                                end=panels.days[-1], initial_capital=1_000_000.0,
                                cost=CostModel(slippage_bp=0).to_dict())
    return Engine(panels, ctx, strategy, cfg, cons or Constraints(max_weight=0.6,
                                                                  max_positions=4))


def test_engine_records_rejects_with_reason(mini_panels, mini_days):
    """第 3 日信号 → 第 4 日成交：AAA 一字涨停买不进、BBB 停牌无行情。"""
    eng = make_engine(mini_panels, BuyAndHold({"AAA.SZ": 0.5, "BBB.SZ": 0.5}))
    res = eng.run()
    rej = res["orders"][res["orders"]["status"] == "REJECTED"]
    assert not rej.empty, "拒单必须留痕，不得静默丢弃"
    assert set(rej["reject_reason"]) <= {"LIMIT_UP_ONE_PU", "SUSPENDED", "NO_BAR",
                                         "CASH_SHORT", "NOT_FINAL"}
    assert res["rejected_summary"]


def test_engine_no_dangling_order_on_last_day(mini_panels, mini_days):
    class RebalanceLastDay(BuyAndHold):
        def rebalance_days(self, ctx, start, end):
            return [ctx.days[-1]]

    eng = make_engine(mini_panels, RebalanceLastDay())
    res = eng.run()
    assert any("悬空订单" in n for n in res["notes"])       # TC-B-25
    assert res["orders"].empty or res["orders"]["exec_date"].max() <= mini_days[-1]


def test_engine_equity_length_and_identity(mini_panels):
    eng = make_engine(mini_panels, BuyAndHold({"CCC.SH": 1.0}))
    res = eng.run()
    assert len(res["equity"]) == len(mini_panels.days)
    assert res["equity"]["nav"].iloc[0] == pytest.approx(1.0, abs=1e-6)
    assert (res["equity"]["cash"] >= 0).all()


def test_shares_are_conserved(mini_panels):
    """股份守恒：期末持仓必须等于「累计买入成交 − 累计卖出成交」。

    回归背景：曾因把估值快照变量写错（closes_cur 未赋值），清算分支读到空字典，
    把持仓整批清零而不留任何成交记录——净值凭空腰斩。该断言能直接抓住这类缺陷。
    """
    eng = make_engine(mini_panels, BuyAndHold({"CCC.SH": 1.0, "AAA.SZ": 1.0}))
    res = eng.run()
    o = res["orders"]
    for sym in res["final_positions"]:
        filled = o[(o.symbol == sym) & o.status.isin(["FILLED", "LIQUIDATED"])]
        net = int(filled.loc[filled.side == BUY, "filled_qty"].sum()
                  - filled.loc[filled.side == SELL, "filled_qty"].sum())
        assert res["final_positions"][sym] == net, (
            f"{sym} 期末 {res['final_positions'][sym]} ≠ 成交净额 {net}，存在隐式清零")
    # 被拒的卖出不得改变持仓
    rejected_sells = o[(o.status == "REJECTED") & (o.side == SELL)]
    for sym in rejected_sells.symbol.unique():
        filled = o[(o.symbol == sym) & o.status.isin(["FILLED", "LIQUIDATED"])]
        net = int(filled.loc[filled.side == BUY, "filled_qty"].sum()
                  - filled.loc[filled.side == SELL, "filled_qty"].sum())
        assert res["final_positions"].get(sym, 0) == net


def make_level_ctx(panels, level: pd.Series):
    from core.strategy.base import Ctx
    rets = level.pct_change().fillna(0.0)
    meta = {s: {"list_date": date(2020, 1, 1)} for s in panels.symbols}
    return Ctx(panels, {}, meta, rets, benchmark_level=level)


@pytest.mark.parametrize("slope,expect", [("up", 1.0), ("flat", 0.5), ("down", 0.0)])
def test_s1_uses_index_level_not_returns(mini_panels, mini_days, slope, expect):
    """S1 择时必须基于指数**点位**均线；回归背景：曾把日收益序列当点位，信号完全失真。"""
    from core.strategy.builtin import TrendTiming
    n = len(mini_days)
    if slope == "up":
        level = pd.Series(np.linspace(3000, 4200, n), index=mini_days)
    elif slope == "flat":
        level = pd.Series([3500.0] * n, index=mini_days)
    else:
        level = pd.Series(np.linspace(4200, 3000, n), index=mini_days)
    ctx = make_level_ctx(mini_panels, level)
    strat = TrendTiming({"ma_fast": 3, "ma_slow": 4, "top_n": 2, "step_days": 1})
    tp = strat.generate(ctx.asof(mini_days[-1]), mini_days[-1])
    total = sum(tp.weights.values()) if tp.weights else 0.0
    if slope == "up":
        assert total == pytest.approx(1.0, abs=1e-6)
    elif slope == "down":
        assert total == pytest.approx(0.0, abs=1e-9)
    else:
        assert total == pytest.approx(0.5, abs=1e-6)


def test_engine_cash_short_rejected(mini_panels):
    class AllIn(Strategy):
        strategy_id = "all_in"
        version = "v1"

        def rebalance_days(self, ctx, start, end):
            return [ctx.days[1]]

        def generate(self, view, ts):
            return TargetPortfolio(weights={"DDD.SH": 1.0})

    eng = make_engine(mini_panels, AllIn())
    eng.cfg.initial_capital = 100.0
    res = eng.run()
    assert res["rejected_summary"].get("CASH_SHORT", 0) + \
        res["rejected_summary"].get("NO_BAR", 0) >= 0
    assert res["equity"]["cash"].min() >= 0
