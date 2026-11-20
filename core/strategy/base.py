"""策略协议与 AsOfView（AP-02：结构性防未来函数）。

AsOfView 只暴露截至信号日的数据切片，并且返回**物理副本**：
策略拿不到 T+1 的任何行，越界访问立即抛 LookaheadAccessError，
而不是依赖 code review 去发现前视偏差。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


class LookaheadAccessError(RuntimeError):
    """QUANT-B-010：策略试图访问信号日之后的数据。"""


@dataclass
class TargetPortfolio:
    weights: dict[str, float] = field(default_factory=dict)
    cash_ratio: float | None = None            # 择时策略可直接给定仓位
    attribution: dict[str, dict] = field(default_factory=dict)
    note: str = ""


class AsOfView:
    def __init__(self, ctx: "Ctx", ts: date):
        self._ctx = ctx
        self.ts = ts
        self._idx = ctx.days.index(ts)

    # ---------------------------------------------------------------- 只读切片
    def window(self, field: str, lookback: int) -> pd.DataFrame:
        if lookback <= 0:
            raise ValueError("lookback 必须为正")
        panel = getattr(self._ctx.panels, field)
        lo = max(0, self._idx - lookback + 1)
        return panel.iloc[lo:self._idx + 1].copy()          # 物理副本，右端点=信号日

    def cross_section(self, field: str) -> pd.Series:
        return getattr(self._ctx.panels, field).iloc[self._idx].copy()

    def factor(self, factor_id: str) -> pd.Series:
        if factor_id not in self._ctx.factors:
            raise KeyError(f"因子未注册：{factor_id}")
        return self._ctx.factors[factor_id].iloc[self._idx].copy()

    def benchmark_window(self, lookback: int) -> pd.Series:
        """指数点位窗口（择时用），右端点=信号日。"""
        lo = max(0, self._idx - lookback + 1)
        return self._ctx.benchmark_level.iloc[lo:self._idx + 1].copy()

    def benchmark_returns(self, lookback: int) -> pd.Series:
        lo = max(0, self._idx - lookback + 1)
        return self._ctx.benchmark.iloc[lo:self._idx + 1].copy()

    def universe(self, top_n: int = 1000, by: str = "amount", lookback: int = 20) -> list[str]:
        return self._ctx.universe(self.ts, top_n=top_n, by=by, lookback=lookback)

    def meta(self, symbol: str) -> dict:
        return self._ctx.meta.get(symbol, {})

    # ---------------------------------------------------------------- 显式禁用
    def next_day_return(self, *a, **k) -> None:
        raise LookaheadAccessError("策略不得读取 T+1 收益；撮合与净值由引擎负责")

    def future(self, *a, **k) -> None:
        raise LookaheadAccessError("AsOfView 不提供未来切片")


class Ctx:
    def __init__(self, panels, factors: dict[str, pd.DataFrame], meta: dict[str, dict],
                 benchmark: pd.Series, blacklist: set[str] | None = None,
                 ic_history: dict[str, pd.Series] | None = None,
                 benchmark_level: pd.Series | None = None):
        self.panels = panels
        self.days = panels.days
        self.factors = factors
        self.meta = meta
        # benchmark = 日收益（绩效口径）；benchmark_level = 指数点位（择时口径）。
        # 二者必须分开：把收益当点位算均线会得到完全无意义的择时信号（S1 回归用例）。
        self.benchmark = benchmark.reindex(panels.days).fillna(0.0).astype("float64")
        self.benchmark_level = (benchmark_level.reindex(panels.days).ffill()
                                if benchmark_level is not None
                                else (1.0 + self.benchmark).cumprod())
        self.blacklist = blacklist or set()
        self.ic_history = ic_history or {}

    def asof(self, ts: date) -> AsOfView:
        if ts not in self.days:
            raise ValueError(f"{ts} 不在回测交易日序列内")
        return AsOfView(self, ts)

    def icir_weights(self, names: list[str], as_of: date, train_days: int = 504,
                     horizon: int = 20) -> dict[str, float]:
        """walk-forward：只用 [T-train, T-1] 的 ICIR 定权重（FR-F-06）。

        IC 序列由服务层一次性向量化预计算，这里仅按日期切片，避免每次调仓重算。
        """
        scores = {}
        for n in names:
            ics = self.ic_history.get(n)
            if ics is None:
                return {}
            hist = ics[(ics.index < as_of) & (ics.index >= _shift(as_of, -train_days))]
            if len(hist) < 60:
                scores[n] = 0.0
                continue
            sd = float(hist.std(ddof=1))
            scores[n] = float(hist.mean() / sd) if sd else 0.0
        tot = sum(abs(v) for v in scores.values())
        if tot == 0:
            return {n: 1.0 / len(names) for n in names}
        return {n: v / tot for n, v in scores.items()}

    def universe(self, as_of: date, top_n: int = 1000, by: str = "amount",
                 lookback: int = 20) -> list[str]:
        """PIT 样本池：只用 as_of 及之前的数据排序。"""
        idx = self.days.index(as_of)
        lo = max(0, idx - lookback + 1)
        p = self.panels
        if by == "amount":
            rank = p.amount.iloc[lo:idx + 1].mean()
        elif by == "mcap":
            cap = (p.close * p.float_share)
            rank = cap.iloc[lo:idx + 1].mean()
        else:
            raise ValueError(f"未知排序口径：{by}")
        allowed = set(rank.index)
        ok = p.close.iloc[idx].notna() & (p.volume.iloc[idx].fillna(0) > 0)
        rank = rank[rank.index.isin(ok[ok].index)]
        df = pd.DataFrame({"symbol": rank.index, "amount_rank": rank.to_numpy()})
        # 并列值必须按 symbol 定序，否则同配置重跑会得到不同篮子（可复现性红线）
        df = df.sort_values(["amount_rank", "symbol"], ascending=[False, True],
                            kind="mergesort")
        return df["symbol"].head(top_n).tolist()


def _shift(d: date, days: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=days)


class Strategy:
    strategy_id = "base"
    version = "v1"

    def params(self) -> dict:
        return {}

    def rebalance_days(self, ctx: Ctx, start: date, end: date) -> list[date]:
        raise NotImplementedError

    def generate(self, view: AsOfView, ts: date) -> TargetPortfolio:
        raise NotImplementedError
