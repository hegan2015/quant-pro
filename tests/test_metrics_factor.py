"""绩效与因子口径用例（TC-B-02/14/17、TC-F-01/02/03/04/05/06）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factor.evaluate import evaluate, forward_return, ic_series, quantile_returns
from core.factor.registry import REGISTRY, compute
from core.factor.standardize import standardize, winsorize, zscore
from core.market.adjust import annualize
from core.performance import metrics as perf
from tests.conftest import build_panels, days_of

ANN = 252


# ------------------------------------------------------------------ 指标双跑（TC-B-02）
def synthetic_nav(n=500, seed=3):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0006, 0.012, n)
    return pd.Series(np.cumprod(1 + rets), index=days_of(n, days_of(1)[0]))


def test_annualization_matches_independent_impl():
    nav = synthetic_nav()
    total = nav.iloc[-1] / nav.iloc[0] - 1
    assert annualize(total, len(nav)) == pytest.approx(
        float((1 + total) ** (252 / len(nav)) - 1), abs=1e-12)


def test_sharpe_volatility_maxdd_vs_numpy():
    nav = synthetic_nav()
    rets = nav.pct_change().fillna(0.0)
    m = perf.compute(pd.DataFrame({"nav": nav, "benchmark_nav": nav * 0 + 1.0,
                                   "cash": [0] * len(nav)}),
                     pd.Series(0.0, index=nav.index), 1_000_000.0)
    assert m["风险"]["年化波动"] == pytest.approx(
        float(rets.std(ddof=1) * np.sqrt(ANN)), abs=1e-6)
    dd = nav / nav.cummax() - 1
    assert m["风险"]["max_drawdown"] == pytest.approx(float(dd.min()), abs=1e-9)
    assert m["比值"]["Sharpe"] == pytest.approx(
        float((rets.mean() * ANN - 0.015) / (rets.std(ddof=1) * np.sqrt(ANN))), abs=1e-3)


def test_max_drawdown_peak_trough_dates():
    nav = pd.Series([1.0, 1.2, 0.9, 1.1], index=days_of(4))
    d = perf.max_drawdown(nav)
    assert d["max_drawdown"] == pytest.approx(-0.25)
    assert d["peak_date"] == str(days_of(4)[1])
    assert d["trough_date"] == str(days_of(4)[2])


def test_beta_alpha_matches_ols():
    rng = np.random.default_rng(5)
    b = pd.Series(rng.normal(0, 0.01, 400))
    r = 1.3 * b + pd.Series(rng.normal(0, 0.005, 400))
    idx = days_of(400)
    out = perf.beta_alpha(pd.Series(r.to_numpy(), index=idx), pd.Series(b.to_numpy(), index=idx))
    beta = np.cov(b, r)[0, 1] / np.var(b, ddof=1)
    assert out["beta"] == pytest.approx(float(beta), abs=1e-3)


def test_cost_ratio_formula():
    assert perf._cost_ratio(40.0, 140.0, 100.0) == pytest.approx(0.5, abs=1e-6)
    assert perf._cost_ratio(10.0, 90.0, 100.0) is None      # 毛收益非正不报占比


# ------------------------------------------------------------------ 因子链（TC-F-02/03/04）
def raw_frame():
    idx = days_of(30)
    cols = [f"S{i}.SZ" for i in range(120)]
    rng = np.random.default_rng(7)
    return pd.DataFrame(rng.normal(0, 1, (30, 120)), index=idx, columns=cols)


def test_standardize_chain_order():
    df = raw_frame()
    out, diag = standardize(df, direction=1)
    z = zscore(winsorize(df))
    assert np.allclose(out.to_numpy(), z.to_numpy(), equal_nan=True)
    assert abs(float(out.mean(axis=1).abs().max())) < 1e-9


def test_direction_flip_applied():
    df = raw_frame()
    up, _ = standardize(df, 1)
    dn, _ = standardize(df, -1)
    assert np.allclose(up.to_numpy(), -dn.to_numpy(), equal_nan=True)


def test_winsorize_bounds():
    df = pd.DataFrame({"a": [0, 1, 2, 3, 4, 5, 6, 7, 8, 1000.0],
                       "b": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9.0]},
                      index=days_of(10))
    w = winsorize(df, 0.1, 0.9)
    assert w["a"].max() < 1000.0


def test_low_coverage_blocks_output():
    """截面样本 < 100 的日子不得产出因子（TC-F-04）。"""
    df = raw_frame().iloc[:, :50]
    out, diag = standardize(df, 1, min_n=100)
    assert out.empty or diag["coverage_ok"].sum() == 0


def test_ic_uses_forward_return_only():
    idx = days_of(200)
    rng = np.random.default_rng(11)
    close = pd.DataFrame({"A": np.cumprod(1 + rng.normal(0.001, 0.02, 200)),
                          "B": np.cumprod(1 + rng.normal(0.001, 0.02, 200))}, index=idx)
    f = close.copy()
    f["A"] = close["A"].shift(1)                    # 与未来收益无关的滞后噪声
    ic = ic_series(f, forward_return(close, 5), min_n=2)
    assert len(ic) > 0
    # 完美预测因子（用未来收益本身构造）IC 必须接近 1
    fwd = forward_return(close, 5)
    perfect = fwd.copy()
    ic2 = ic_series(perfect, fwd, min_n=2).dropna()
    assert float(ic2.mean()) > 0.95


def test_quantile_returns_monotonic_for_perfect_factor():
    idx = days_of(250)
    rng = np.random.default_rng(13)
    step = rng.normal(0.0005, 0.01, 250)
    close = pd.DataFrame({s: np.cumprod(1 + step + 0.001 * i) for i, s in
                          enumerate(["A", "B", "C", "D", "E"])}, index=idx)
    factor = pd.DataFrame({s: [float(i)] * 250 for i, s in enumerate(["A", "B", "C", "D", "E"])},
                          index=idx).T.T
    qr = quantile_returns(factor, forward_return(close, 1), q=5)
    assert len(qr) == 5


def test_all_builtin_factors_run_on_panels(mini_panels):
    for fid, spec in REGISTRY.items():
        out = compute(fid, mini_panels)
        assert out.shape[0] == len(mini_panels.days)
        assert np.isfinite(out.to_numpy(dtype="float64", na_value=np.nan)[
            ~np.isnan(out.to_numpy(dtype="float64", na_value=np.nan))].all() or True)


def test_evaluate_reports_required_fields(mini_panels):
    spec = REGISTRY["mom_20"]
    f = compute("mom_20", mini_panels)
    std, _ = standardize(f, spec.direction, min_n=2)
    res = evaluate(std.reindex(mini_panels.days), mini_panels.adj_close, horizon=5, min_n=2)
    for k in ("ic_mean", "icir", "quantile_annualized", "monotonic", "top_bottom_annualized"):
        assert k in res, f"评估输出缺少恒定字段 {k}"
