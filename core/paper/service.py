"""模拟盘服务（FR-P-01..08）。

与回测共用 `core.engine.execution` 撮合内核（FR-P-07）：账户结算 = 以已发布信号为
目标组合、从账户起点确定性重跑到结算日。重跑幂等（订单按 idempotency_key upsert，
流水按 ref 去重只追加），因此「重放」天然不污染历史。

对账不信任引擎内部账本：从**落库产物**（流水 + 持仓 + 复权价）独立重算现金/市值/净值，
与落库净值比对，差额 > 1bp 写 recon_check 并给出追溯信息（FR-P-05）。
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import pandas as pd

from core.config import settings
from core.engine.execution import BacktestConfig, Engine
from core.engine.panels import load as load_panels
from core.services import candidate_symbols, load_meta
from core.store.duckdb_store import DuckDBStore
from core.strategy.base import Ctx, Strategy, TargetPortfolio
from core.strategy.constraints import Constraints

RECON_TOLERANCE_BP = 1.0


def _d(v) -> date:
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "date") and not isinstance(v, date):
        return v.date()
    return v


class _PublishedSignals(Strategy):
    strategy_id = "published_signals"
    version = "v1"

    def __init__(self, by_date: dict[date, dict[str, float]]):
        self.by_date = by_date

    def rebalance_days(self, ctx, start, end):
        return sorted(d for d in self.by_date if start <= d <= end)

    def generate(self, view, ts):
        return TargetPortfolio(weights=dict(self.by_date.get(ts, {})))


def create_account(store: DuckDBStore, name: str, capital: float, strategy_id: str,
                   start_date: date, cost: dict | None = None) -> str:
    account_id = "acct-" + uuid.uuid4().hex[:8]
    store.create_paper_account({
        "account_id": account_id, "name": name, "initial_capital": capital,
        "cost_model": json.dumps(cost or settings.load().cost), "strategy_id": strategy_id,
        "start_date": start_date, "status": "active", "created_at": pd.Timestamp.now(),
    })
    return account_id


def _signal_targets(store: DuckDBStore, account_id: str, start: date, upto: date
                    ) -> dict[date, dict[str, float]]:
    sigs = store.query_df(
        "SELECT run_id, trade_date FROM signal_run WHERE status='published'"
        " AND trade_date >= ? AND trade_date < ? ORDER BY trade_date", [start, upto])
    out: dict[date, dict[str, float]] = {}
    for r in sigs.itertuples():
        items = store.signal_items(r.run_id)
        out[_d(r.trade_date)] = dict(zip(items.symbol, items.target_weight))
    return out


def settle(store: DuckDBStore, account_id: str, upto: date) -> dict:
    acct = store.get_paper_account(account_id)
    start = _d(acct["start_date"])
    if upto < start:
        raise ValueError("结算日早于账户起点")
    targets = _signal_targets(store, account_id, start, upto)
    cands = candidate_symbols(store, start, n=3000)
    panels = load_panels(store, start, upto, symbols=cands)
    meta = load_meta(store)
    bench = settings.load_benchmark_returns(store, settings.load()["BENCHMARK"], start, upto)
    ctx = Ctx(panels, {}, meta, bench)
    cfg = BacktestConfig(strategy_id=acct["strategy_id"], start=start, end=upto,
                         initial_capital=acct["initial_capital"],
                         cost=acct["cost_model"], params={"daily_positions": True})
    res = Engine(panels, ctx, _PublishedSignals(targets), cfg,
                 Constraints(max_weight=1.0, max_positions=200)).run()

    # 订单：幂等键 = 账户|信号日|执行日|标的|方向
    orders = res["orders"].copy()
    if not orders.empty:
        base = int(store.scalar("SELECT coalesce(max(order_id),0) FROM paper_order") or 0)
        orders["order_id"] = range(base + 1, base + 1 + len(orders))
        orders["account_id"] = account_id
        sig_ids = {rid: _d(td) for rid, td in _sig_ids(store, start, upto).items()}
        orders["signal_run_id"] = orders["ts"].map(
            lambda d: next((rid for rid, td in sig_ids.items() if td == _d(d)), None))
        orders["idempotency_key"] = (account_id + "|" + orders["ts"].astype(str) + "|"
                                     + orders["exec_date"].astype(str) + "|"
                                     + orders["symbol"] + "|" + orders["side"])
        store.save_paper_orders(orders[[
            "order_id", "account_id", "signal_run_id", "ts", "exec_date", "symbol", "side",
            "req_qty", "filled_qty", "price", "gross", "fee", "status", "reject_reason",
            "idempotency_key"]])

    eq = res["equity"].reset_index()
    eq["account_id"] = account_id
    store.save_paper_equity(eq[["account_id", "ts", "nav", "cash", "mv", "exposure",
                               "turnover", "fee"]])
    pos = res["positions"].copy()
    if not pos.empty:
        pos["account_id"] = account_id
        pos["sellable_qty"] = pos["qty"]
        pos["cost"] = pos["cost"]
        store.save_paper_positions(pos[["account_id", "ts", "symbol", "qty", "sellable_qty",
                                        "cost", "mv", "weight"]])

    # 流水：只追加，按 ref（订单幂等键）去重
    existing = set(store.paper_ledger(account_id)["ref"].dropna())
    filled = orders[orders.status.isin(["FILLED", "LIQUIDATED"])] if not orders.empty else orders
    rows = []
    for o in filled.itertuples():
        if o.idempotency_key in existing:
            continue
        amt = -(o.gross + o.fee) if o.side == "BUY" else (o.gross - o.fee)
        rows.append({"account_id": account_id, "ts": o.exec_date, "kind": o.side,
                     "symbol": o.symbol, "qty": o.filled_qty, "amount": float(amt),
                     "ref": o.idempotency_key})
    if rows:
        store.append_paper_ledger(pd.DataFrame(rows))

    recon = reconcile(store, account_id, panels)
    return {"account_id": account_id, "upto": str(upto), "signals": len(targets),
            "orders": int(len(orders)), "days": int(len(eq)),
            "nav": float(eq["nav"].iloc[-1]) if len(eq) else 1.0,
            "recon_max_bp": recon["max_abs_bp"], "recon_open": recon["open"]}


def _sig_ids(store: DuckDBStore, start: date, upto: date) -> dict[str, date]:
    df = store.query_df("SELECT run_id, trade_date FROM signal_run WHERE status='published'"
                        " AND trade_date >= ? AND trade_date < ?", [start, upto])
    return dict(zip(df.run_id, df.trade_date))


def reconcile(store: DuckDBStore, account_id: str, panels=None) -> dict:
    """从落库产物独立重算，与落库净值比对（不读引擎内部账本）。"""
    acct = store.get_paper_account(account_id)
    eq = store.paper_equity(account_id)
    if eq.empty:
        return {"max_abs_bp": 0.0, "open": 0, "rows": 0}
    ledger = store.paper_ledger(account_id)
    if not ledger.empty:
        ledger["ts"] = pd.to_datetime(ledger["ts"])
    pos = store.paper_positions(account_id)
    if not pos.empty:
        pos["ts"] = pd.to_datetime(pos["ts"])
    if panels is None:
        panels = load_panels(store, _d(acct["start_date"]), _d(eq.ts.max()),
                             symbols=sorted(set(pos.symbol)))
    rows = []
    for r in eq.itertuples():
        ts = pd.Timestamp(r.ts)
        cash = acct["initial_capital"] + float(
            ledger[ledger.ts <= ts]["amount"].sum()) if not ledger.empty \
            else acct["initial_capital"]
        day_pos = pos[pos.ts == ts]
        mv = 0.0
        for p in day_pos.itertuples():
            if p.symbol in panels.adj_close.columns and r.ts in panels.adj_close.index:
                px = panels.adj_close.loc[r.ts, p.symbol]
                if pd.notna(px):
                    mv += p.qty * float(px)
        nav_re = (cash + mv) / acct["initial_capital"]
        diff_bp = (nav_re - r.nav) / r.nav * 10000 if r.nav else 0.0
        status = "ok" if abs(diff_bp) <= RECON_TOLERANCE_BP else "open"
        rows.append({"run_id": account_id, "ts": r.ts, "expected": round(nav_re, 8),
                     "actual": round(float(r.nav), 8), "diff_bp": round(float(diff_bp), 4),
                     "traced": json.dumps({"cash_recomputed": round(cash, 2),
                                           "mv_recomputed": round(mv, 2),
                                           "n_positions": int(len(day_pos))},
                                          ensure_ascii=False),
                     "status": status})
    df = pd.DataFrame(rows)
    store.save_recon(df)
    return {"max_abs_bp": round(float(df.diff_bp.abs().max()), 4),
            "open": int((df.status == "open").sum()), "rows": int(len(df))}


def replay(store: DuckDBStore, account_id: str, from_date: date) -> str:
    """重放 = 新建独立账户副本，原账户零写入（FR-P-06 / TC-P-09）。"""
    src = store.get_paper_account(account_id)
    new_id = create_account(store, src["name"] + "-replay", src["initial_capital"],
                            src["strategy_id"], from_date, src["cost_model"])
    return new_id
