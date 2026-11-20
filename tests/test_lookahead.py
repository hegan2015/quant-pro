"""未来函数门禁用例（TC-B-11/20/21/22/23/24、FR-S-01 结构性隔离）。"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core.engine.lookahead_guard import (
    lag1_strategy_lookahead, lag3_factor_source, lag4_factor_truncation, _truncate)
from core.factor.registry import FactorSpec, REGISTRY, compute
from core.strategy.base import AsOfView, Ctx, LookaheadAccessError, Strategy, TargetPortfolio
from tests.engine_helpers import BuyAndHold, LeakStrategy


def ctx_of(panels):
    bench = pd.Series(0.0, index=panels.days)
    meta = {s: {"list_date": date(2020, 1, 1)} for s in panels.symbols}
    return Ctx(panels, {}, meta, bench)


# ------------------------------------------------------------------ AsOfView 隔离
def test_asofview_right_edge_is_signal_day(mini_panels, mini_days):
    view = ctx_of(mini_panels).asof(mini_days[2])
    w = view.window("close", 3)
    assert w.index[0] == mini_days[0] and w.index[-1] == mini_days[2]
    assert len(w) == 3


def test_asofview_window_is_physical_copy(mini_panels, mini_days):
    view = ctx_of(mini_panels).asof(mini_days[2])
    w = view.window("close", 3)
    w.iloc[0, 0] = -999.0
    assert mini_panels.close.iloc[0, 0] != -999.0, "切片必须是副本，不得改写面板"


def test_asofview_rejects_future_apis(mini_panels, mini_days):
    view = ctx_of(mini_panels).asof(mini_days[2])
    with pytest.raises(LookaheadAccessError):
        view.next_day_return()
    with pytest.raises(LookaheadAccessError):
        view.future()


def test_asofview_unknown_date_raises(mini_panels):
    with pytest.raises(ValueError):
        ctx_of(mini_panels).asof(date(1999, 1, 1))


def test_truncate_physically_removes_future(mini_panels, mini_days):
    cut = _truncate(mini_panels, mini_days[2])
    assert cut.days == mini_days[:3]
    assert mini_panels.close.shape[0] == len(mini_days)


# ------------------------------------------------------------------ LAG-1
def test_lag1_passes_for_clean_strategy(mini_panels):
    ctx = ctx_of(mini_panels)
    res = lag1_strategy_lookahead(BuyAndHold(), ctx, [mini_panels.days[1]], sample=1)
    assert res.status == "pass"


def test_lag1_catches_leaky_strategy(mini_panels):
    """变异测试：策略读 T+1 收盘价选股 → 必须 FAIL（TC-B-20）。"""
    ctx = ctx_of(mini_panels)
    days = [mini_panels.days[1], mini_panels.days[3]]
    res = lag1_strategy_lookahead(LeakStrategy(), ctx, days, sample=2)
    assert res.status == "FAIL", "前视策略必须被门禁拦下"
    assert "截断未来数据后变化" in res.detail


# ------------------------------------------------------------------ LAG-3 静态扫描
def test_lag3_catches_injected_shift(tmp_path, monkeypatch):
    """变异测试：往 core/strategy 注入含 shift(-1) 的文件 → 静态扫描必须命中。"""
    import core.strategy as strat_pkg
    target = None
    for p in map(lambda x: __import__("pathlib").Path(x), strat_pkg.__path__):
        target = p / "_mutant_probe.py"
        break
    target.write_text("import pandas as pd\nx = df.shift(-1)\n", encoding="utf-8")
    try:
        res = lag3_factor_source()
        assert res.status == "FAIL"
        assert "_mutant_probe.py" in res.detail
    finally:
        target.unlink()
    assert lag3_factor_source().status == "pass"


# ------------------------------------------------------------------ LAG-4 因子右端点
def test_lag4_passes_for_builtin_factors(mini_panels):
    res = lag4_factor_truncation(mini_panels, ["mom_20", "vol_60", "size_float"], sample=3)
    assert res.status in ("pass", "skipped")


def test_lag4_catches_leaky_factor(mini_panels):
    """变异测试：因子用未来价 → 截断重算必须不一致（TC-B-23）。"""
    leaky = FactorSpec("leaky_probe", "探针", 1, ("adj_close",),
                       lambda p: p.adj_close.shift(-1))
    REGISTRY["leaky_probe"] = leaky
    try:
        res = lag4_factor_truncation(mini_panels, ["leaky_probe"], sample=3)
        assert res.status == "FAIL"
    finally:
        REGISTRY.pop("leaky_probe")


def test_factor_compute_on_truncated_matches_full_at_edge(mini_panels, mini_days):
    """因子在 T 日的值 = 只用 ≤T 数据重算的 T 日值（逐值一致）。"""
    cut = _truncate(mini_panels, mini_days[3])
    full = compute("mom_20", mini_panels)
    trunc = compute("mom_20", cut)
    ts = mini_days[3]
    if ts in full.index and ts in trunc.index:
        a, b = full.loc[ts].dropna(), trunc.loc[ts].dropna()
        common = a.index.intersection(b.index)
        assert np.allclose(a[common], b[common], equal_nan=True)
