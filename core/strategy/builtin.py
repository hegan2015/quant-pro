"""内置基线策略（FR-S-02）。

三条策略同时作为引擎验收：S1 验择时与仓位、S2 验多因子与月度调仓、S3 验行业约束。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from core.factor.evaluate import walk_forward_weights
from core.strategy.base import AsOfView, Ctx, Strategy, TargetPortfolio


def month_end_days(days: list[date]) -> list[date]:
    s = pd.Series(days)
    per = s.dt.to_period("M") if hasattr(s, "dt") else None
    out = []
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt is None or (d.year, d.month) != (nxt.year, nxt.month):
            out.append(d)
    return out


def every_n_days(days: list[date], n: int) -> list[date]:
    return days[::max(1, n)]


class TrendTiming(Strategy):
    """S1：基准双均线择时 × 流动性篮子（仓位 0/50/100%）。"""

    strategy_id = "s1_trend"
    version = "v1"

    def __init__(self, params: dict | None = None):
        self.p = {"ma_fast": 20, "ma_slow": 60, "top_n": 50, "step_days": 5,
                  "half_position": 0.5}
        self.p.update(params or {})

    def params(self) -> dict:
        return dict(self.p)

    def rebalance_days(self, ctx: Ctx, start: date, end: date) -> list[date]:
        return every_n_days([d for d in ctx.days if start <= d <= end], self.p["step_days"])

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        b = view.benchmark_window(self.p["ma_slow"] + 1)
        if len(b) < self.p["ma_slow"]:
            return TargetPortfolio(note="基准历史不足，维持空仓")
        fast = float(b.rolling(self.p["ma_fast"]).mean().iloc[-1])
        slow = float(b.rolling(self.p["ma_slow"]).mean().iloc[-1])
        ratio = 1.0 if fast > slow else self.p["half_position"] if fast > slow * 0.98 else 0.0
        uni = view.universe(top_n=self.p["top_n"], by="amount")
        if not uni or ratio <= 0:
            return TargetPortfolio(weights={}, cash_ratio=ratio,
                                   note=f"双均线 {fast:.1f}/{slow:.1f} → 仓位 {ratio:.0%}")
        w = {s: ratio / len(uni) for s in uni}
        return TargetPortfolio(weights=w, note=f"趋势仓位 {ratio:.0%}，篮子 {len(uni)} 只")


class MultiFactor(Strategy):
    """S2：多因子打分月度选股（walk-forward ICIR 加权，Top N 等权）。"""

    strategy_id = "s2_multifactor"
    version = "v1"

    def __init__(self, params: dict | None = None):
        self.p = {
            "top_n": 30, "candidate_mult": 4, "weighting": "icir", "train_days": 504,
            "horizon": 20,
            "factors": {"mom_20": 0.25, "mom_60": 0.15, "vol_60": 0.15,
                        "size_float": 0.15, "turnover_20": 0.15, "amihud_20": 0.15},
        }
        self.p.update(params or {})

    def params(self) -> dict:
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.p.items()}

    def rebalance_days(self, ctx: Ctx, start: date, end: date) -> list[date]:
        return month_end_days([d for d in ctx.days if start <= d <= end])

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        names = list(self.p["factors"])
        missing = [n for n in names if n not in view._ctx.factors]
        if missing:
            raise KeyError(f"因子未计算：{missing}（先跑 quant factor）")
        cand = view.universe(top_n=self.p["top_n"] * self.p["candidate_mult"], by="amount")
        if len(cand) < self.p["top_n"]:
            return TargetPortfolio(note=f"候选池仅 {len(cand)} 只，不足 {self.p['top_n']}")

        weights: dict[str, float] = {}
        if self.p["weighting"] == "icir":
            weights = view._ctx.icir_weights(names, ts, self.p["train_days"],
                                             self.p["horizon"])
            if not weights:   # 未预计算 IC（如单测直接构造 Ctx）时回退到即时计算
                weights = walk_forward_weights(
                    {n: view._ctx.factors[n] for n in names},
                    view._ctx.panels.adj_close, ts,
                    train_days=self.p["train_days"], horizon=self.p["horizon"])
        else:
            weights = {n: 1.0 / len(names) for n in names}

        score = pd.Series(0.0, index=cand)
        contribs: dict[str, pd.Series] = {}
        for n, w in weights.items():
            z = view.factor(n).reindex(cand)
            part = z.fillna(0.0) * float(w)
            score = score.add(part)
            contribs[n] = part
        top = score.sort_values(ascending=False).head(self.p["top_n"])
        unit = 1.0 / len(top)
        return TargetPortfolio(
            weights={s: unit for s in top.index},
            attribution={s: {n: round(float(v.get(s, np.nan)), 4) for n, v in contribs.items()}
                         for s in top.index},
            note=f"因子加权 {'equal' if self.p['weighting'] != 'icir' else 'ICIR'} "
                 f"打分 Top{len(top)}，等权 {unit:.2%}")


class IndustryRotation(Strategy):
    """S3：一级行业相对强度轮动（Top 行业 × 行业内动量前列）。"""

    strategy_id = "s3_rotation"
    version = "v1"

    def __init__(self, params: dict | None = None):
        self.p = {"lookback": 60, "top_industries": 5, "per_industry": 6,
                  "crowding_penalty": 0.5}
        self.p.update(params or {})

    def params(self) -> dict:
        return dict(self.p)

    def rebalance_days(self, ctx: Ctx, start: date, end: date) -> list[date]:
        return month_end_days([d for d in ctx.days if start <= d <= end])

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        uni = view.universe(top_n=800, by="amount")
        ind_map = {s: view.meta(s).get("industry_l1") for s in uni}
        ind_map = {s: v for s, v in ind_map.items() if v}
        if len(ind_map) < 50:
            return TargetPortfolio(note="行业分类覆盖不足，跳过轮动")
        mom = view.window("adj_close", self.p["lookback"] + 1)
        ret = (mom.iloc[-1] / mom.iloc[0] - 1.0).reindex(list(ind_map)).dropna()
        amt = view.window("amount", self.p["lookback"]).mean().reindex(ret.index)
        grp = pd.Series(ind_map)
        ind_ret = ret.groupby(grp).mean()
        ind_amt = amt.groupby(grp).mean()
        crowd = (ind_amt / ind_amt.sum()).rank(pct=True)
        adj_ret = ind_ret - self.p["crowding_penalty"] * crowd * ind_ret.abs()
        tops = adj_ret.sort_values(ascending=False).head(self.p["top_industries"]).index
        weights: dict[str, float] = {}
        per = 1.0 / (len(tops) * self.p["per_industry"])
        mom60 = view.factor("mom_60") if "mom_60" in view._ctx.factors else ret
        for ind in tops:
            members = [s for s, v in ind_map.items() if v == ind]
            ranked = mom60.reindex(members).dropna().sort_values(ascending=False)
            for s in ranked.head(self.p["per_industry"]).index:
                weights[s] = per
        return TargetPortfolio(weights=weights,
                               note=f"行业轮动 {list(tops)}，每行业 {self.p['per_industry']} 只")


STRATEGIES = {"s1_trend": TrendTiming, "s2_multifactor": MultiFactor,
              "s3_rotation": IndustryRotation}


def build(strategy_id: str, params: dict | None = None) -> Strategy:
    if strategy_id not in STRATEGIES:
        raise KeyError(f"策略未注册：{strategy_id}（可选 {list(STRATEGIES)}）")
    return STRATEGIES[strategy_id](params)
