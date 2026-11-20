"""因子评估（FR-F-04/05）：IC 序列、ICIR、分层收益、相关性。

注意：forward return 只存在于评估代码里，策略侧通过 AsOfView 物理隔离拿不到（AP-02）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.market.calendar import ANN_VOL


def forward_return(adj_close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """T→T+horizon 收益，用于 IC；末日为 NaN（自然剔除）。"""
    c = adj_close.ffill()
    return c.shift(-horizon) / c - 1.0


def ic_matrix(factor: pd.DataFrame, fwd: pd.DataFrame, min_n: int = 100) -> pd.Series:
    """向量化截面秩相关（Spearman）。

    逐日 pandas corr 在 1500 列 × 2400 日 × 6 因子 × 120 次调仓的规模下不可接受，
    这里一次算完整条 IC 序列，策略侧按日期切片取历史（FR-F-06 walk-forward）。
    """
    idx = factor.index.intersection(fwd.index)
    cols = factor.columns.intersection(fwd.columns)
    f = factor.loc[idx, cols]
    r = fwd.loc[idx, cols]
    both = f.notna() & r.notna()
    x = f.where(both).rank(axis=1).to_numpy(dtype="float64")
    y = r.where(both).rank(axis=1).to_numpy(dtype="float64")
    mask = ~(np.isnan(x) | np.isnan(y))
    x0, y0 = np.where(mask, x, 0.0), np.where(mask, y, 0.0)
    nn = mask.sum(axis=1).astype("float64")
    sx, sy = x0.sum(1), y0.sum(1)
    sxx, syy, sxy = (x0 * x0).sum(1), (y0 * y0).sum(1), (x0 * y0).sum(1)
    cov = sxy - sx * sy / np.where(nn > 0, nn, 1)
    vx = sxx - sx * sx / np.where(nn > 0, nn, 1)
    vy = syy - sy * sy / np.where(nn > 0, nn, 1)
    den = np.sqrt(vx * vy)
    with np.errstate(divide="ignore", invalid="ignore"):
        ic = np.where((den > 0) & (nn >= min_n), cov / den, np.nan)
    return pd.Series(ic, index=f.index).dropna()


def ic_series(factor: pd.DataFrame, fwd: pd.DataFrame, min_n: int = 100) -> pd.Series:
    return ic_matrix(factor, fwd, min_n=min_n)


def quantile_returns(factor: pd.DataFrame, daily_ret: pd.DataFrame, q: int = 5
                     ) -> pd.DataFrame:
    """按因子分 q 组，统计各组日均收益（前瞻）与年化。"""
    common = factor.index.intersection(daily_ret.index)
    acc = {i: [] for i in range(1, q + 1)}
    for i, ts in enumerate(common[:-1]):
        f = factor.loc[ts]
        nxt = daily_ret.loc[common[i + 1]]
        m = f.notna() & nxt.notna()
        if int(m.sum()) < q * 20:
            continue
        ranks = pd.qcut(f[m].rank(method="first"), q, labels=False) + 1
        for grp in range(1, q + 1):
            sel = nxt[m][ranks == grp]
            if len(sel):
                acc[grp].append(float(sel.mean()))
    return pd.DataFrame({
        "group": list(acc),
        "mean_daily": [np.mean(v) if v else np.nan for v in acc.values()],
        "annualized": [np.mean(v) * ANN_VOL if v else np.nan for v in acc.values()],
    })


def max_correlation(factor: pd.DataFrame, others: dict[str, pd.DataFrame],
                    sample_days: int = 60) -> tuple[str, float]:
    """与已注册因子的最大截面相关性（FR-F-05 去重）。"""
    if not others:
        return "", 0.0
    days = factor.index[-sample_days:]
    best, best_id = 0.0, ""
    for fid, other in others.items():
        vals = []
        for ts in days:
            if ts not in other.index:
                continue
            a, b = factor.loc[ts], other.loc[ts]
            m = a.notna() & b.notna()
            if int(m.sum()) < 50:
                continue
            vals.append(float(pd.Series(a[m].to_numpy()).corr(pd.Series(b[m].to_numpy()))))
        if vals:
            c = float(np.mean(vals))
            if abs(c) > abs(best):
                best, best_id = c, fid
    return best_id, best


def evaluate(factor: pd.DataFrame, adj_close: pd.DataFrame, horizon: int = 20,
             window_days: int = 750, min_n: int = 100) -> dict:
    """字段恒定输出（缺项为 None + note），报告渲染不依赖分支（UI-DESIGN §7 空值规范）。"""
    fwd = forward_return(adj_close, horizon)
    ics = ic_series(factor, fwd, min_n=min_n).tail(window_days)
    base = {"horizon": horizon, "n_periods": int(len(ics)), "ic_mean": None, "ic_std": None,
            "icir": None, "t_stat": None, "ic_pos_ratio": None,
            "quantile_annualized": None, "monotonic": None, "top_bottom_annualized": None}
    if ics.empty:
        base["note"] = "有效截面不足或前瞻收益不可得"
        return base
    mean, std = float(ics.mean()), float(ics.std(ddof=1))
    qr = quantile_returns(factor, forward_return(adj_close, 1))
    ann = qr["annualized"].to_numpy()
    mono = bool(np.all(np.diff(ann) > 0)) or bool(np.all(np.diff(ann) < 0))
    top_bottom = float(ann[-1] - ann[0]) if len(ann) == qr["group"].max() else None
    out = base | {
        "n_periods": int(len(ics)),
        "ic_mean": round(mean, 5), "ic_std": round(std, 5),
        "icir": round(mean / std, 4) if std else None,
        "t_stat": round(mean / std * np.sqrt(len(ics)), 3) if std else None,
        "ic_pos_ratio": round(float((ics > 0).mean()), 4),
        "quantile_annualized": [round(float(x), 4) for x in ann],
        "monotonic": mono,
        "top_bottom_annualized": round(top_bottom, 4) if top_bottom is not None else None,
    }
    return out


def walk_forward_weights(factors: dict[str, pd.DataFrame], adj_close: pd.DataFrame,
                         as_of, train_days: int = 504, horizon: int = 20) -> dict[str, float]:
    """用 [T-train, T-1] 的 ICIR 定权重（FR-F-06：严禁使用 T 之后信息）。"""
    days = list(adj_close.index)
    idx = days.index(as_of)
    lo = max(0, idx - train_days)
    window_days = days[lo:idx]
    if len(window_days) < 120:
        return {fid: 1.0 / len(factors) for fid in factors}
    fwd = forward_return(adj_close.loc[days[lo:min(idx, len(days) - 1) + horizon + 1]], horizon)
    scores = {}
    for fid, f in factors.items():
        ics = ic_series(f.loc[window_days], fwd, min_n=50)
        if len(ics) < 60:
            scores[fid] = 0.0
            continue
        sd = float(ics.std(ddof=1))
        scores[fid] = float(ics.mean() / sd) if sd else 0.0
    tot = sum(abs(v) for v in scores.values())
    if tot == 0:
        return {fid: 1.0 / len(factors) for fid in factors}
    return {fid: v / tot for fid, v in scores.items()}
