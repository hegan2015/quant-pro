"""每日信号服务（FR-G-01..06）。

信号 = 策略在信号日收盘可得信息下的目标组合；发布前置校验全部在服务端完成，
任一不过即拒绝发布并给出原因清单（不生成 published）。
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

import pandas as pd

from core.config import settings
from core.engine.execution import BacktestConfig, Engine
from core.engine.lookahead_guard import run_gates
from core.engine.panels import load as load_panels
from core.factor.registry import REGISTRY
from core.risk import engine as risk
from core.services import compute_factors, load_meta
from core.store.duckdb_store import DuckDBStore
from core.strategy.base import Ctx, Strategy, TargetPortfolio
from core.strategy.builtin import build as build_strategy
from core.strategy.constraints import Constraints

LOOKBACK_DAYS = 420          # 因子/均线所需历史窗口（自然日）
MIN_COVERAGE = 0.99


def _as_date(v) -> date:
    """库读回的日期可能是 Timestamp/datetime（二者都是 date 的子类），必须显式取 .date()。"""
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date()
    if isinstance(v, date):
        return v
    raise TypeError(f"无法归一为日期：{type(v)}")


class PublishBlocked(RuntimeError):
    """QUANT-S-001：发布前置校验不过。"""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("；".join(reasons))


class _SignalAt(Strategy):
    """只在指定信号日产出一次目标组合（复用引擎装配，保证与回测同口径）。"""

    strategy_id = "signal_at"
    version = "v1"

    def __init__(self, inner: Strategy, day: date):
        self.inner = inner
        self.day = day

    def params(self) -> dict:
        return self.inner.params()

    def rebalance_days(self, ctx, start, end):
        return [self.day] if start <= self.day <= end else []

    def generate(self, view, ts):
        return self.inner.generate(view, ts)


def target_at(store: DuckDBStore, strategy_id: str, params: dict, trade_date: date,
              universe_size: int = 1000) -> tuple[dict[str, float], dict, Ctx]:
    st = settings.load()
    start = trade_date - timedelta(days=LOOKBACK_DAYS)
    from core.services import candidate_symbols
    cands = candidate_symbols(store, start, n=max(universe_size * 3, 1500))
    panels = load_panels(store, start, trade_date, symbols=cands)
    if trade_date not in panels.days:
        raise ValueError(f"{trade_date} 非交易日或无行情")
    ids = list(params.get("factors") or REGISTRY)
    factors = compute_factors(store, panels, [i for i in ids if i in REGISTRY], persist=False)
    meta = load_meta(store)
    bench_ret = settings.load_benchmark_returns(store, st["BENCHMARK"], start, trade_date)
    bench_level = settings.load_benchmark_level(store, st["BENCHMARK"], start, trade_date)
    from core.factor.evaluate import forward_return, ic_matrix
    ic_history = {fid: ic_matrix(factors[fid], forward_return(panels.adj_close, 20), min_n=50)
                  for fid in factors}
    ctx = Ctx(panels, factors, meta, bench_ret, ic_history=ic_history,
              benchmark_level=bench_level)
    inner = build_strategy(strategy_id, {k: v for k, v in params.items() if k != "constraints"})
    cfg = BacktestConfig(strategy_id=strategy_id, start=panels.days[0], end=trade_date,
                         universe=f"LIQUID_{universe_size}",
                         params={**params, "signal_only": True},
                         cost=st.cost, initial_capital=st["INITIAL_CAPITAL"])
    cons = Constraints.from_dict(params.get("constraints", st.constraints))
    res = Engine(panels, ctx, _SignalAt(inner, trade_date), cfg, cons).run()
    if not res["signals"]:
        raise ValueError(f"{trade_date} 未产出目标组合（策略当日空仓或候选不足）")
    weights = res["signals"][-1]["raw"]
    gates = run_gates(inner, ctx, [trade_date], panels, res["positions"],
                      [i for i in ids if i in REGISTRY], has_fundamental=False)
    return weights, gates, ctx


def precheck(store: DuckDBStore, trade_date: date, weights: dict[str, float],
             gates: dict, account_id: str | None = None) -> list[dict]:
    """四项前置校验，返回 [{name, status, detail}]。"""
    out = []
    trade_date = _as_date(trade_date)
    latest = _as_date(store.latest_trade_date())
    cov = store.query_df(
        "SELECT count(*) n FROM daily_bar WHERE ts = ? AND is_final", [trade_date])
    n_final = int(cov["n"].iloc[0]) if not cov.empty else 0
    n_uni = len(store.universe(trade_date))
    ratio = n_final / max(n_uni, 1)
    # 新鲜度 = 该信号日数据终态覆盖达标，且信号日不晚于最新交易日（不得发未来信号）；
    # 不要求「信号日==最新日」，否则历史信号无法发布、模拟盘无法结算历史区间
    fresh = trade_date <= latest and ratio >= MIN_COVERAGE
    out.append({"name": "数据新鲜度", "status": "pass" if fresh else "FAIL",
                "detail": f"信号日={trade_date}，最新交易日={latest}，"
                          f"终态覆盖 {n_final}/{n_uni}={ratio:.2%}"})
    blocking = store.query_df(
        "SELECT count(*) n FROM data_issue WHERE ts = ? AND blocking AND status='open'",
        [trade_date])
    nb = int(blocking["n"].iloc[0]) if not blocking.empty else 0
    out.append({"name": "阻断 issue", "status": "pass" if nb == 0 else "FAIL",
                "detail": f"当日 open 阻断项 {nb}"})
    out.append({"name": "未来函数门禁", "status": gates["lookahead_status"],
                "detail": "；".join(f"{c['lag']}:{c['status']}" for c in gates["checks"])})
    meta = load_meta(store)
    positions = {}
    for sym, w in weights.items():
        m = meta.get(sym, {})
        positions[sym] = {"weight": w, "is_st": bool(m.get("is_st")),
                          "age_lt": False, "in_blacklist": False}
    snap = risk.Snapshot(trade_date=trade_date, account_id=account_id or "*",
                         positions=positions)
    hits = risk.evaluate(store, snap)
    bad = [h for h in hits if h["action"] in ("REJECT_ORDER", "BLOCK_BUY")]
    out.append({"name": "风控预检", "status": "pass" if not bad else "FAIL",
                "detail": f"命中 {len(bad)} 项" + (f"：{[h['rule_id'] for h in bad][:5]}" if bad else "")})
    return out


def build_signal(store: DuckDBStore, strategy_id: str, params: dict, trade_date: date,
                 actor: str = "system", account_id: str | None = None,
                 universe_size: int = 1000) -> dict:
    weights, gates, ctx = target_at(store, strategy_id, params, trade_date, universe_size)
    checks = precheck(store, trade_date, weights, gates, account_id)
    run_id = "sig-" + trade_date.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    cur: dict[str, float] = {}
    if account_id:
        pos = store.paper_positions(account_id)
        if not pos.empty:
            last = pos[pos.ts == pos.ts.max()]
            cur = dict(zip(last.symbol, last.weight))
    items = pd.DataFrame([{
        "symbol": s, "target_weight": w, "current_weight": cur.get(s, 0.0),
        "delta": w - cur.get(s, 0.0), "attribution": json.dumps({}, ensure_ascii=False),
    } for s, w in sorted(weights.items())])
    store.create_signal({
        "run_id": run_id, "trade_date": trade_date, "strategy_id": strategy_id,
        "version": "v1", "status": "draft", "reason": None,
        "checks": json.dumps(checks, ensure_ascii=False), "source_run_id": None,
        "created_by": actor, "created_at": pd.Timestamp.now(), "published_at": None,
    })
    store.write_signal_items(run_id, items)
    return {"run_id": run_id, "trade_date": str(trade_date), "status": "draft",
            "checks": checks, "n_items": len(items),
            "turnover": round(float(items.delta.abs().sum()) / 2, 4)}


def publish(store: DuckDBStore, run_id: str, actor: str, confirm: bool = False) -> dict:
    rec = store.get_signal(run_id)
    if rec["status"] != "draft":
        raise PublishBlocked([f"状态为 {rec['status']}，只有 draft 可发布"])
    if not confirm:
        raise PublishBlocked(["缺少 confirm=true 二次确认"])
    items = store.signal_items(run_id)
    weights = dict(zip(items.symbol, items.target_weight))
    gates = {"lookahead_status": "pass", "checks": []}
    for c in rec["checks"]:
        if c["name"] == "未来函数门禁":
            gates = {"lookahead_status": c["status"], "checks": []}
    checks = precheck(store, _as_date(rec["trade_date"]), weights, gates)
    failed = [c for c in checks if c["status"] == "FAIL"]
    if failed:
        store.create_signal({**rec, "checks": json.dumps(checks, ensure_ascii=False)})
        raise PublishBlocked([f"{c['name']}：{c['detail']}" for c in failed])
    store.set_signal_status(run_id, "published", actor)
    return {"run_id": run_id, "status": "published", "checks": checks}


def withdraw(store: DuckDBStore, run_id: str, actor: str, reason: str) -> dict:
    rec = store.get_signal(run_id)
    if rec["status"] != "published":
        raise PublishBlocked([f"状态为 {rec['status']}，只有 published 可撤回"])
    if not reason:
        raise PublishBlocked(["撤回必须带原因"])
    store.set_signal_status(run_id, "withdrawn", actor, reason)
    return {"run_id": run_id, "status": "withdrawn", "reason": reason}
