"""风控规则引擎（FR-R-01..07）。判定在服务端，事件留痕，熔断需人工解除。

动作语义：
- REJECT_ORDER：拒该笔订单（留痕，不静默）
- BLOCK_BUY：熔断，只拒绝新增买入，不强平已有持仓（FR-R-03）
- REDUCE：要求减仓（生成减仓目标，交组合层执行）
- ALERT：仅告警留痕
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from core.store.duckdb_store import DuckDBStore

ACTIONS = ("REJECT_ORDER", "BLOCK_BUY", "REDUCE", "ALERT")
OPS = (">", ">=", "<", "<=", "==", "in")


@dataclass
class Rule:
    rule_id: str
    name: str
    metric: str
    op: str
    threshold: float
    action: str
    priority: int = 50
    enabled: bool = True
    version: int = 1
    scope: str = "*"

    def hit(self, value: float) -> bool:
        if not self.enabled:
            return False
        t = self.threshold
        return {">": value > t, ">=": value >= t, "<": value < t,
                "<=": value <= t, "==": value == t,
                "in": bool(value)}.get(self.op, False)


BUILTIN: list[Rule] = [
    Rule("R-BLACKLIST-01", "黑名单", "symbol.in_blacklist", "in", 1, "REJECT_ORDER", 5),
    Rule("R-NEWLISTING-01", "次新禁买", "symbol.age_days_lt", "in", 1, "REJECT_ORDER", 6),
    Rule("R-ST-01", "ST 禁买", "symbol.is_st", "in", 1, "REJECT_ORDER", 7),
    Rule("R-DRAWDOWN-01", "水位期最大回撤熔断", "portfolio.max_drawdown", ">", 0.20,
         "BLOCK_BUY", 10),
    Rule("R-WEIGHT-01", "单票权重上限", "position.weight", ">", 0.10, "REJECT_ORDER", 20),
    Rule("R-INDUSTRY-01", "行业主动偏离", "industry.active_deviation", ">", 0.08,
         "REDUCE", 30),
    Rule("R-TURNOVER-01", "单日换手上限", "portfolio.turnover_daily", ">", 0.60,
         "REJECT_ORDER", 40),
]


def ensure_rules(store: DuckDBStore) -> int:
    rows = []
    for r in BUILTIN:
        rows.append({**asdict(r), "scope": r.scope})
    import pandas as pd
    return store.upsert_rules(pd.DataFrame(rows))


@dataclass
class Snapshot:
    """风控判定的输入快照（全部由服务端计算，前端不可伪造）。"""
    trade_date: date
    account_id: str = "*"
    portfolio_max_drawdown: float = 0.0
    portfolio_turnover_daily: float = 0.0
    positions: dict[str, dict] = field(default_factory=dict)   # sym -> {weight, is_st, age_lt, in_blacklist}
    industry_deviation: dict[str, float] = field(default_factory=dict)


def evaluate(store: DuckDBStore, snap: Snapshot) -> list[dict]:
    """返回命中清单（含订单级与组合级），并写 risk_event（open）。"""
    rules = store.load_rules()
    hits: list[dict] = []
    breaker = circuit_breaker_open(store, snap.account_id)
    for sym, p in snap.positions.items():
        metrics = {
            "symbol.in_blacklist": float(p.get("in_blacklist", False)),
            "symbol.age_days_lt": float(p.get("age_lt", False)),
            "symbol.is_st": float(p.get("is_st", False)),
            "position.weight": float(p.get("weight", 0.0)),
        }
        for r in rules:
            if r.metric in metrics and r.hit(metrics[r.metric]):
                hits.append({"rule_id": r.rule_id, "symbol": sym, "action": r.action,
                             "metric": r.metric, "value": metrics[r.metric],
                             "priority": r.priority})
    if breaker:
        hits.append({"rule_id": "R-DRAWDOWN-01", "symbol": "*", "action": "BLOCK_BUY",
                     "metric": "portfolio.circuit_breaker", "value": 1.0, "priority": 10})
    port_metrics = {"portfolio.max_drawdown": snap.portfolio_max_drawdown,
                    "portfolio.turnover_daily": snap.portfolio_turnover_daily}
    for r in rules:
        if r.metric in port_metrics and r.hit(port_metrics[r.metric]):
            hits.append({"rule_id": r.rule_id, "symbol": "*", "action": r.action,
                         "metric": r.metric, "value": port_metrics[r.metric],
                         "priority": r.priority})
    for ind, dev in snap.industry_deviation.items():
        for r in rules:
            if r.metric == "industry.active_deviation" and r.hit(dev):
                hits.append({"rule_id": r.rule_id, "symbol": ind, "action": r.action,
                             "metric": r.metric, "value": dev, "priority": r.priority})
    if hits:
        store.write_risk_events(snap.trade_date, snap.account_id, hits)
    return sorted(hits, key=lambda h: h["priority"])


def circuit_breaker_open(store: DuckDBStore, account_id: str = "*") -> bool:
    """存在未解除的 BLOCK_BUY 事件即视为熔断中（人工 ack 后才解除）。"""
    return store.count_open_block_buy(account_id) > 0


def order_blocked(hits: list[dict], symbol: str) -> str | None:
    """订单级拒绝原因（组合级 BLOCK_BUY 对买入生效）。"""
    for h in hits:
        if h["action"] == "REJECT_ORDER" and h["symbol"] in (symbol, "*"):
            return h["rule_id"]
    return None


def buy_blocked(hits: list[dict]) -> bool:
    return any(h["action"] == "BLOCK_BUY" for h in hits)
