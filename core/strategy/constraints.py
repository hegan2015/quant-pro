"""组合约束（FR-S-05/06 / DETAILED-DESIGN §8）。

迭代裁剪而非优化器求解：日线月度调仓场景下足够，且每一步都可解释、可留痕。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass
class Constraints:
    max_weight: float = 0.10
    min_positions: int = 10
    max_positions: int = 50
    min_cash: float = 0.0
    max_turnover: float = 0.60
    max_industry_dev: float = 0.08
    blacklist: set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, d: dict) -> "Constraints":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict:
        return {k: (sorted(v) if isinstance(v, set) else v)
                for k, v in self.__dict__.items()}


def cap_weights(w: pd.Series, max_weight: float) -> pd.Series:
    """单票上限：超限部分回摊给未触限标的，**保持权重合计不变**（择时仓位不被抹平）。"""
    total = float(w.sum())
    if total <= 0:
        return w
    w = w.astype(float).copy()
    for _ in range(100):
        over = w > max_weight + 1e-12
        if not over.any():
            break
        excess = float((w[over] - max_weight).sum())
        w[over] = max_weight
        room = w[w < max_weight - 1e-12]
        if room.empty or room.sum() <= 0:
            break
        w[room.index] = room + excess * room / float(room.sum())
    return w / float(w.sum()) * total


def apply_industry_cap(w: pd.Series, industry: dict[str, str], cap: float,
                       bench: pd.Series | None = None) -> tuple[pd.Series, list[str]]:
    """行业主动偏离上限：超出部分等比压缩，保持权重合计不变。"""
    notes: list[str] = []
    total = float(w.sum())
    if total <= 0:
        return w, notes
    if not industry or cap <= 0:
        return w, notes
    def label(sym: str) -> str:
        v = industry.get(sym)
        return v if isinstance(v, str) and v else "未分类"

    grp = pd.Series({s: label(s) for s in w.index})
    base = (bench.groupby([label(x) for x in bench.index]).sum() if bench is not None
            else pd.Series(0.0, index=sorted(set(grp.tolist()))))
    for _ in range(20):
        cur = w.groupby(grp).sum()
        dev = cur - base.reindex(cur.index).fillna(0.0)
        over = dev[dev > cap]
        if over.empty:
            return w, notes
        for ind in over.index:
            members = w[grp[grp == ind].index]
            scale = float((base.get(ind, 0.0) + cap) / cur[ind])
            w[members.index] = members * scale
            notes.append(f"行业 {ind} 主动偏离 {float(dev[ind]):.3f} > {cap} → 压缩 {scale:.3f}")
        w = w / float(w.sum()) * total if w.sum() > 0 else w
    return w, notes


def select_top(w: pd.Series, max_positions: int, min_positions: int) -> tuple[pd.Series, str]:
    if len(w) <= max_positions:
        return w, ""
    keep = w.sort_values(ascending=False).head(max_positions)
    return keep / keep.sum(), f"持仓数 {len(w)} > {max_positions} → 取权重前列 {max_positions}"


def apply_turnover_limit(new_w: pd.Series, cur_w: pd.Series, max_turnover: float
                         ) -> tuple[pd.Series, list[str]]:
    """换手上限：按权重差从大到小成交，超限部分跳过（FR-S-06 / SKIPPED_TURNOVER）。"""
    diff = (new_w - cur_w).fillna(new_w.index.map(lambda s: 0.0))
    gross = float(diff.abs().sum()) / 2.0
    if gross <= max_turnover or gross == 0:
        return new_w, []
    order = diff.abs().sort_values(ascending=False)
    budget, out, skipped = max_turnover * 2.0, new_w.copy(), []
    for sym in order.index:
        room = min(abs(float(diff[sym])), budget)
        if room < abs(float(diff[sym])) - 1e-9 and budget > 0:
            pass
        out[sym] = float(cur_w.get(sym, 0.0)) + (room if diff[sym] > 0 else -room)
        budget -= room
        if budget <= 0:
            skipped = [s for s in order.index if abs(float(new_w[s] - out[s])) > 1e-6]
            break
    out = out.clip(lower=0)
    total = float(out.sum())
    if total > 0:
        out = out / total
    return out, ([f"单边换手 {gross:.1%} > {max_turnover:.1%} → 部分调仓被跳过 "
                  f"({len(skipped)} 只)"] if skipped else
                 [f"单边换手 {gross:.1%} > {max_turnover:.1%} → 已按权重差优先序裁剪"])


def build_target(scores: pd.Series, cons: Constraints, industry: dict[str, str],
                 cur_w: pd.Series | None = None, bench_w: pd.Series | None = None,
                 tradable: pd.Series | None = None
                 ) -> tuple[pd.Series, list[str]]:
    """打分 → 目标权重（含全部约束），返回权重与逐条裁剪说明。"""
    notes: list[str] = []
    w = scores.dropna().astype(float)
    if tradable is not None:
        blocked = w.index[~tradable.reindex(w.index).fillna(False).astype(bool)]
        if len(blocked):
            notes.append(f"不可买入标的剔除 {len(blocked)} 只")
            w = w.drop(index=blocked)
    if cons.blacklist:
        hit = [s for s in w.index if s in cons.blacklist]
        if hit:
            notes.append(f"黑名单剔除 {len(hit)} 只")
            w = w.drop(index=hit)
    if w.empty:
        return w, notes + ["候选集为空"]
    w = w[w > 0] if (w > 0).any() else w
    n = min(cons.max_positions, max(len(w), 0))
    w = w.sort_values(ascending=False).head(n)
    w = w / w.sum() * (1.0 - cons.min_cash)
    w, note = select_top(w, cons.max_positions, cons.min_positions)
    if note:
        notes.append(note)
    w = cap_weights(w, cons.max_weight)
    w2, ind_notes = apply_industry_cap(w, industry, cons.max_industry_dev, bench_w)
    w = w2
    notes += ind_notes
    if len(w) < cons.min_positions:
        notes.append(f"持仓数 {len(w)} < 下限 {cons.min_positions}")
    if cur_w is not None and cons.max_turnover > 0:
        w, tn = apply_turnover_limit(w, cur_w, cons.max_turnover)
        notes += tn
    return w, notes
