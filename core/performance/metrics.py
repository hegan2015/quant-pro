"""绩效指标（FR-B-09 / DETAILED-DESIGN §9）。

口径：年化 252 交易日；rf 默认 1.5%；简单收益用于净值与业绩。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.market.calendar import ANN_VOL
from core.market.adjust import annualize


def drawdown(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def max_drawdown(nav: pd.Series) -> dict:
    dd = drawdown(nav)
    if dd.empty:
        return {"max_drawdown": None}
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    after = nav.loc[trough:]
    recovered = after[after >= nav.loc[peak]]
    rec_date = recovered.index[0] if len(recovered) else None
    return {
        "max_drawdown": float(dd.min()),
        "peak_date": str(peak), "trough_date": str(trough),
        "recovery_date": str(rec_date) if rec_date is not None else None,
        "recovery_days": int(len(nav.loc[trough:rec_date])) if rec_date is not None else None,
        "underwater_days": int((dd < 0).sum()),
    }


def sharpe(rets: pd.Series, rf_annual: float = 0.015) -> float:
    if len(rets) < 2:
        return float("nan")
    ex = rets.mean() * ANN_VOL - rf_annual
    vol = float(rets.std(ddof=1) * np.sqrt(ANN_VOL))
    return float(ex / vol) if vol else float("nan")


def sortino(rets: pd.Series, rf_annual: float = 0.015) -> float:
    downside = rets[rets < 0]
    if len(downside) < 2:
        return float("nan")
    dvol = float(np.sqrt((downside ** 2).mean()) * np.sqrt(ANN_VOL))
    return float((rets.mean() * ANN_VOL - rf_annual) / dvol) if dvol else float("nan")


def var95(rets: pd.Series) -> float:
    return float(np.percentile(rets, 5)) if len(rets) > 20 else float("nan")


def beta_alpha(rets: pd.Series, bench: pd.Series, rf_annual: float = 0.015) -> dict:
    j = pd.concat([rets, bench], axis=1).dropna()
    if len(j) < 60:
        return {"beta": None, "alpha_annual": None}
    rf_d = rf_annual / ANN_VOL
    y = j.iloc[:, 0] - rf_d
    x = j.iloc[:, 1] - rf_d
    cov = float(np.cov(x, y)[0, 1])
    var = float(np.var(x, ddof=1))
    beta = cov / var if var else float("nan")
    alpha_d = float(y.mean() - beta * x.mean())
    return {"beta": round(beta, 4), "alpha_annual": round((1 + alpha_d) ** ANN_VOL - 1, 4)}


def tracking_stats(rets: pd.Series, bench: pd.Series) -> dict:
    j = pd.concat([rets, bench], axis=1).dropna()
    if len(j) < 60:
        return {"te": None, "info_ratio": None}
    active = j.iloc[:, 0] - j.iloc[:, 1]
    te = float(active.std(ddof=1) * np.sqrt(ANN_VOL))
    ann_excess = float(active.mean() * ANN_VOL)
    return {"te": round(te, 4), "info_ratio": round(ann_excess / te, 4) if te else None,
            "annual_excess": round(ann_excess, 4)}


def trade_stats(orders: pd.DataFrame, nav_series: pd.Series, initial: float) -> dict:
    """换手分母用「平均资产元」= 平均净值比例 × 初始资金，而非净值比例本身。"""
    filled = orders[orders["status"] == "FILLED"] if not orders.empty else orders
    total_fee = float(orders["fee"].sum()) if not orders.empty else 0.0
    gross = float(orders["gross"].sum()) if not orders.empty else 0.0
    years = max(len(nav_series) / ANN_VOL, 1e-9)
    avg_asset = float(nav_series.mean()) * initial if len(nav_series) else initial
    one_side = gross / 2.0          # 换手口径为单边成交额 / 平均资产（REQUIREMENTS §8）
    return {
        "orders_total": int(len(orders)), "orders_filled": int(len(filled)),
        "orders_rejected": int(len(orders) - len(filled)),
        "total_fee": round(total_fee, 2),
        "annual_turnover": round(one_side / avg_asset / years, 4) if avg_asset else None,
        "total_gross_traded": round(gross, 2),
        "avg_trade_size": round(gross / len(filled), 2) if len(filled) else None,
    }


def empty_metrics(reason: str) -> dict:
    """空窗口的恒定结构输出：报告渲染不依赖分支，缺项显示 —（UI-DESIGN §7）。"""
    return {g: {} for g in ("收益", "风险", "比值", "交易", "基准与结构")} | {"note": reason}


def compute(equity: pd.DataFrame, benchmark_ret: pd.Series, initial_capital: float,
            rf_annual: float = 0.015, orders: pd.DataFrame | None = None) -> dict:
    if equity is None or equity.empty or "nav" not in equity:
        return empty_metrics("该区间无净值数据（区间过短或全部被过滤）")
    nav = equity["nav"].astype(float)
    rets = nav.pct_change().fillna(0.0)
    bench_nav = equity["benchmark_nav"].astype(float) if "benchmark_nav" in equity \
        else (1.0 + benchmark_ret).cumprod()
    bench_ret = bench_nav.pct_change().fillna(0.0)
    total = float(nav.iloc[-1] - 1.0)
    b_total = float(bench_nav.iloc[-1] - 1.0)
    n = len(nav)
    ann = annualize(total, n)
    b_ann = annualize(b_total, n)
    vol = float(rets.std(ddof=1) * np.sqrt(ANN_VOL))
    dd = max_drawdown(nav)
    calmar = round(ann / abs(dd["max_drawdown"]), 4) if dd.get("max_drawdown") else None
    out = {
        "收益": {
            "累计收益": round(total, 6), "年化收益": round(ann, 6),
            "基准累计收益": round(b_total, 6), "基准年化收益": round(b_ann, 6),
            "年化超额": round(ann - b_ann, 6), "交易日数": n,
        },
        "风险": {
            "年化波动": round(vol, 6), "下行波动": round(
                float(np.sqrt((rets[rets < 0] ** 2).mean()) * np.sqrt(ANN_VOL)), 6),
            **{k: v for k, v in dd.items()}, "VaR95_日": round(var95(rets), 6),
        },
        "比值": {
            "Sharpe": round(sharpe(rets, rf_annual), 4), "Sortino": round(sortino(rets, rf_annual), 4),
            "Calmar": calmar, **beta_alpha(rets, bench_ret, rf_annual),
            **tracking_stats(rets, bench_ret),
        },
        "交易": trade_stats(orders if orders is not None else pd.DataFrame(), nav,
                          initial_capital),
        "基准与结构": {"基准": "000300", "超额曲线末值": round(float(
            (nav / bench_nav).iloc[-1]), 6)},
    }
    out["交易"]["成本占毛收益"] = _cost_ratio(
        out["交易"].get("total_fee", 0.0), float(nav.iloc[-1]) * initial_capital,
        initial_capital)
    return out


def _cost_ratio(fee: float, final_value: float, initial_capital: float) -> float | None:
    """成本占毛收益 = Σ费用 / (期末资产 − 期初 + Σ费用)（体检表红线 ≤ 40%）。"""
    gross_gain = final_value - initial_capital + fee
    if gross_gain <= 0:
        return None
    return round(float(fee / gross_gain), 4)


def monthly_returns(equity: pd.DataFrame) -> pd.DataFrame:
    nav = equity["nav"].astype(float)
    ix = pd.to_datetime(nav.index)
    m = nav.groupby([ix.year, ix.month]).last()
    first = nav.groupby(ix.year).first()
    out = m.unstack()
    pct = out.pct_change(axis=1)
    for y in pct.index:
        if y in first.index and 1 in pct.columns:
            pct.loc[y, 1] = out.loc[y, 1] / float(first.loc[y]) - 1.0
    return pct.fillna(0.0)
