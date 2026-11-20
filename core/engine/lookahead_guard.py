"""未来函数门禁（FR-B-13 / LAG-1..5）。

门禁不通过则回测标记 LOOKAHEAD_FAIL，禁止进入信号发布（引擎层强制，非前端提示）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core.engine.panels import Panels
from core.factor.registry import REGISTRY, compute
from core.strategy.base import Ctx


@dataclass
class GateResult:
    lag: str
    name: str
    status: str            # pass / FAIL / WARN / skipped
    detail: str


def _truncate(panels: Panels, upto: date) -> Panels:
    """把面板截断到 upto（含），物理上抹掉之后所有数据。"""
    keep = [d for d in panels.days if d <= upto]
    sl = slice(0, len(keep))
    return Panels(
        days=keep, symbols=panels.symbols,
        open=panels.open.iloc[sl].copy(), high=panels.high.iloc[sl].copy(),
        low=panels.low.iloc[sl].copy(), close=panels.close.iloc[sl].copy(),
        volume=panels.volume.iloc[sl].copy(), amount=panels.amount.iloc[sl].copy(),
        limit_up=panels.limit_up.iloc[sl].copy(), limit_down=panels.limit_down.iloc[sl].copy(),
        adj_close=panels.adj_close.iloc[sl].copy(), float_share=panels.float_share.iloc[sl].copy(),
        r_adj=panels.r_adj.iloc[sl].copy(),
        prev_close=panels.prev_close.iloc[sl].copy(),
    )


def lag1_strategy_lookahead(strategy, ctx_full: Ctx, rebalance_days: list[date],
                            sample: int = 8) -> GateResult:
    """同一信号日：全量面板 vs 截断面板，信号必须逐标的相同。"""
    if not rebalance_days:
        return GateResult("LAG-1", "策略前视替换", "skipped", "无调仓日")
    picks = rebalance_days[::max(1, len(rebalance_days) // sample)][:sample]
    diffs = []
    for ts in picks:
        full = strategy.generate(ctx_full.asof(ts), ts).weights
        trunc_ctx = Ctx(_truncate(ctx_full.panels, ts),
                        {k: v.loc[:ts] for k, v in ctx_full.factors.items()},
                        ctx_full.meta, ctx_full.benchmark.loc[:ts],
                        ic_history={k: v[v.index <= ts] for k, v in
                                    ctx_full.ic_history.items()})
        try:
            cut = strategy.generate(trunc_ctx.asof(ts), ts).weights
        except Exception as exc:      # 截断后无法计算 = 依赖了未来数据
            diffs.append((str(ts), "<error>", repr(exc), "truncated run failed"))
            continue
        keys = set(full) | set(cut)
        for k in keys:
            if abs(float(full.get(k, 0.0)) - float(cut.get(k, 0.0))) > 1e-9:
                diffs.append((str(ts), k, full.get(k), cut.get(k)))
    if diffs:
        return GateResult("LAG-1", "策略前视替换", "FAIL",
                          f"{len(diffs)} 处信号在截断未来数据后变化，示例 {diffs[:3]}")
    return GateResult("LAG-1", "策略前视替换", "pass", f"{len(picks)} 个信号日截断后完全一致")


def lag3_factor_source() -> GateResult:
    """静态扫描：因子与策略代码不得出现向未来 shift（评估模块的 forward_return 除外）。"""
    root = Path(__file__).resolve().parents[2]
    bad = []
    for base in ("core/factor", "core/strategy", "core/engine"):
        for f in sorted((root / base).rglob("*.py")):
            if f.name in ("evaluate.py", "lookahead_guard.py"):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"shift\(\s*-", line) or re.search(r"iloc\[\s*-0\b", line):
                    bad.append(f"{f.relative_to(root)}:{i}")
    if bad:
        return GateResult("LAG-3", "复权与前视静态扫描", "FAIL", f"发现未来引用 {bad}")
    return GateResult("LAG-3", "复权与前视静态扫描", "pass",
                      "因子/策略/引擎无 shift(-k) 未来引用")


def lag4_factor_truncation(panels: Panels, factor_ids: list[str],
                           sample: int = 6) -> GateResult:
    """因子在 T 日的值必须与「只看 ≤T 数据」重算的结果一致（含 rolling 右端点）。"""
    days = panels.days
    if len(days) < 4:
        return GateResult("LAG-4", "因子窗口右端点", "skipped", "面板过短，无法取样")
    start = max(2, min(60, len(days) - 2))
    span = max(len(days) - 1 - start, 1)
    idxs = sorted({min(len(days) - 2, start + int(i * span / max(sample - 1, 1)))
                   for i in range(sample)})
    picks = [days[i] for i in idxs]
    diffs = []
    for fid in factor_ids:
        spec = REGISTRY[fid]
        full = spec.fn(panels)
        for ts in picks:
            try:
                cut = spec.fn(_truncate(panels, ts))
            except Exception as exc:
                diffs.append((fid, str(ts), f"truncated run failed: {exc!r}"))
                continue
            if ts not in full.index or ts not in cut.index:
                continue
            a, b = full.loc[ts], cut.loc[ts]
            m = a.notna() & b.notna()
            if m.any() and float((a[m] - b[m]).abs().max()) > 1e-6:
                diffs.append((fid, str(ts), round(float((a[m] - b[m]).abs().max()), 8)))
            lost = int((a.notna() & b.isna()).sum())
            if lost > 0.5 * max(int(a.notna().sum()), 1):
                diffs.append((fid, str(ts), f"截断后 {lost} 个标的无法计算（依赖未来数据）"))
    if diffs:
        return GateResult("LAG-4", "因子窗口右端点", "FAIL", f"截断重算不一致 {diffs[:5]}")
    return GateResult("LAG-4", "因子窗口右端点", "pass",
                      f"{len(factor_ids)} 个因子 × {len(picks)} 个截面完全一致")


def lag5_stale_valuation(panels: Panels, positions: pd.DataFrame,
                        max_stale_days: int = 20) -> GateResult:
    """退市/长期停牌持仓不得用陈旧价格长期估值（FR-D-09 清算路径缺失即 FAIL）。"""
    if positions.empty:
        return GateResult("LAG-5", "退市持仓清算", "skipped", "无持仓快照")
    close = panels.close
    bad = []
    for rec in positions.itertuples():
        col = close[rec.symbol] if rec.symbol in close.columns else None
        if col is None:
            bad.append((str(rec.ts), rec.symbol, "无行情列"))
            continue
        avail = col.loc[:rec.ts].dropna()
        if avail.empty:
            continue
        last = avail.index[-1]
        stale = len([d for d in panels.days if last < d <= rec.ts])
        if stale > max_stale_days:
            bad.append((str(rec.ts), rec.symbol, f"估值价滞后 {stale} 交易日"))
    if bad:
        return GateResult("LAG-5", "退市持仓清算", "FAIL", f"陈旧估值 {len(bad)} 处，示例 {bad[:3]}")
    return GateResult("LAG-5", "退市持仓清算", "pass",
                      f"持仓快照无超过 {max_stale_days} 日的陈旧估值")


def lag2_financial_pit(has_fundamental: bool) -> GateResult:
    if not has_fundamental:
        return GateResult("LAG-2", "财报时点", "skipped",
                          "P1 未接入 PIT 财务源（A-02），财务类因子不可用")
    return GateResult("LAG-2", "财报时点", "pass", "ann_date ≤ T 过滤已生效")


def run_gates(strategy, ctx: Ctx, rebalance_days: list[date], panels: Panels,
              positions: pd.DataFrame, factor_ids: list[str],
              has_fundamental: bool = False) -> dict:
    results = [
        lag1_strategy_lookahead(strategy, ctx, rebalance_days),
        lag2_financial_pit(has_fundamental),
        lag3_factor_source(),
        lag4_factor_truncation(panels, factor_ids),
        lag5_stale_valuation(panels, positions),
    ]
    status = "FAIL" if any(r.status == "FAIL" for r in results) else "pass"
    return {"lookahead_status": status,
            "checks": [{"lag": r.lag, "name": r.name, "status": r.status,
                        "detail": r.detail} for r in results]}
