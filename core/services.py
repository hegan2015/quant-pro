"""用例编排：数据装配 → 因子 → 回测 → 门禁 → 绩效 → 敏感性 → 体检 → 落库。

CLI 与后续 API 共用本层（DETAILED-DESIGN §20：CLI 不再绕 HTTP）。
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from core.config import settings
from core.engine.execution import BacktestConfig, Engine
from core.engine.lookahead_guard import run_gates
from core.engine.panels import Panels, load as load_panels
from core.factor.evaluate import evaluate as evaluate_factor, walk_forward_weights
from core.factor.registry import REGISTRY, compute as compute_factor, meta_frame
from core.factor.standardize import standardize
from core.performance import metrics as perf
from core.store.duckdb_store import DuckDBStore
from core.strategy.base import Ctx
from core.strategy.builtin import build as build_strategy
from core.strategy.constraints import Constraints


def candidate_symbols(store: DuckDBStore, start: date, n: int = 1500,
                      look_days: int = 250) -> list[str]:
    """样本池在窗口起点用「过去 look_days 日成交额」确定（PIT，不用全样本信息挑选）。"""
    end0 = start + timedelta(days=int(look_days * 7 / 5) + 15)
    # 必须带 symbol 二级排序键：并列值下 SQL 返回顺序不定，会让同配置重跑得到不同篮子
    rows = store.query(
        "SELECT symbol, avg(amount) a FROM daily_bar WHERE ts BETWEEN ? AND ?"
        " AND amount > 0 GROUP BY symbol ORDER BY a DESC NULLS LAST, symbol ASC LIMIT ?",
        [start, end0, n])
    return sorted(r[0] for r in rows)


def _as_date(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def load_meta(store: DuckDBStore) -> dict[str, dict]:
    inst = store.instruments()
    out = {}
    for r in inst.itertuples():
        out[r.symbol] = {
            "name": r.name, "industry_l1": r.industry_l1,
            "list_date": _as_date(r.list_date),
            "is_st": bool(r.is_st) if r.is_st is not None else False,
            "board": r.board,
        }
    return out


def compute_factors(store: DuckDBStore, panels: Panels, ids: list[str],
                    persist: bool = True) -> dict[str, pd.DataFrame]:
    meta = meta_frame()
    if persist:
        store.upsert_factor_meta(meta)
    out: dict[str, pd.DataFrame] = {}
    for fid in ids:
        spec = REGISTRY[fid]
        raw = compute_factor(fid, panels)
        std, _diag = standardize(raw, spec.direction)
        std = std.reindex(panels.days).reindex(columns=panels.symbols)
        out[fid] = std
        if persist:
            store.write_factor(fid, std)
    return out


def _rebase(equity: pd.DataFrame) -> pd.DataFrame:
    """段内净值/基准从首值归一（perf.compute 以 nav.iloc[-1]-1 计累计收益）。"""
    if equity.empty:
        return equity
    out = equity.copy()
    out["nav"] = out["nav"] / float(out["nav"].iloc[0])
    if "benchmark_nav" in out:
        out["benchmark_nav"] = out["benchmark_nav"] / float(out["benchmark_nav"].iloc[0])
    return out


def _engine_run(panels: Panels, ctx: Ctx, strategy, cfg: BacktestConfig,
                constraints: Constraints) -> dict:
    eng = Engine(panels, ctx, strategy, cfg, constraints)
    return eng.run()


def backtest(store: DuckDBStore, strategy_id: str, params: dict | None = None,
             start: date | None = None, end: date | None = None,
             universe_size: int = 1000, cost: dict | None = None,
             initial_capital: float = 1_000_000.0, benchmark_code: str = "000300",
             factor_ids: list[str] | None = None, seed: int = 7,
             train_end: date | None = None, persist: bool = True,
             sensitivity: bool = True) -> dict:
    st = settings.load()
    start = start or date.fromisoformat(st["START_DATE"])
    end = end or date.fromisoformat(st["END_DATE"])
    train_end = train_end or date.fromisoformat(st["TRAIN_END"])
    if not (start < train_end < end):
        raise ValueError(
            f"训练/留出区间重叠或退化：需 start({start}) < train_end({train_end}) < end({end})")
    params = dict(params or {})
    params.setdefault("constraints", st.constraints)
    cons = Constraints.from_dict(params["constraints"])
    t0 = time.monotonic()

    timings: dict[str, float] = {}
    t = time.monotonic()
    cands = candidate_symbols(store, start, n=max(universe_size * 3, 1500))
    panels = load_panels(store, start, end, symbols=cands)
    timings["load_panels"] = round(time.monotonic() - t, 1)
    ids = factor_ids or list(params.get("factors") or REGISTRY)
    ids = [f for f in ids if f in REGISTRY]
    t = time.monotonic()
    factors = compute_factors(store, panels, ids, persist=persist)
    timings["compute_factors"] = round(time.monotonic() - t, 1)
    meta = load_meta(store)
    bench_ret = settings.load_benchmark_returns(store, benchmark_code, start, end)
    bench_level = settings.load_benchmark_level(store, benchmark_code, start, end)
    from core.factor.evaluate import forward_return, ic_matrix
    ic_history = {fid: ic_matrix(factors[fid], forward_return(panels.adj_close, 20),
                                 min_n=50) for fid in factors}
    ctx = Ctx(panels, factors, meta, bench_ret, ic_history=ic_history,
              benchmark_level=bench_level)

    strategy = build_strategy(strategy_id, {k: v for k, v in params.items()
                                            if k != "constraints"})
    cfg = BacktestConfig(strategy_id=strategy_id, version=strategy.version,
        params=params, start=start, end=end,
        universe=f"LIQUID_{universe_size}", universe_size=universe_size,
        initial_capital=initial_capital, cost=cost or st.cost, benchmark=benchmark_code,
        seed=seed, train_end=train_end)
    t = time.monotonic()
    res = _engine_run(panels, ctx, strategy, cfg, cons)
    timings["engine"] = round(time.monotonic() - t, 1)
    equity, orders = res["equity"], res["orders"]

    is_in = equity.index <= train_end
    metrics_full = perf.compute(equity, bench_ret, initial_capital, st["RF_ANNUAL"], orders)
    # 分段指标必须重定基：净值与基准都从该段起点归一，否则段内收益被全期累计值污染
    metrics_in = perf.compute(_rebase(equity[is_in]),
                              bench_ret[bench_ret.index <= train_end],
                              initial_capital, st["RF_ANNUAL"],
                              orders[orders["ts"] <= train_end] if not orders.empty else orders)
    cap_at_split = float(equity.loc[is_in, "nav"].iloc[-1] * initial_capital) \
        if is_in.any() else initial_capital
    metrics_oos = perf.compute(
        _rebase(equity[~is_in]), bench_ret[bench_ret.index > train_end], cap_at_split,
        st["RF_ANNUAL"], orders[orders["ts"] > train_end] if not orders.empty else orders)

    gates = run_gates(strategy, ctx, strategy.rebalance_days(ctx, start, end), panels,
                      res["positions"], ids, has_fundamental=False)
    sens = cost_sensitivity(store, strategy_id, params, start, end, universe_size,
                            initial_capital, benchmark_code, ids, seed, train_end) \
        if sensitivity else {}
    checklist = run_checklist(metrics_full, metrics_in, metrics_oos, sens, equity)
    contributions = symbol_contributions(orders, res["positions"], panels)

    out = {
        "run_id": cfg.run_id, "config": cfg.to_dict(),
        # run_id 是实例标识而非配置，必须排除，否则同配置重跑哈希必然不同
        "config_hash": settings.config_hash(
            {k: v for k, v in cfg.to_dict().items() if k != "run_id"},
            store.data_version(start, end)),
        "data_version": store.data_version(start, end),
        "code_digest": settings.code_digest(),
        "elapsed_sec": round(time.monotonic() - t0, 1), "timings": timings,
        "panels": {"days": len(panels.days), "symbols": len(panels.symbols),
                   "memory_mb": panels.memory_mb()},
        "metrics": metrics_full, "metrics_in_sample": metrics_in,
        "metrics_oos": metrics_oos, "lookahead": gates,
        "cost_sensitivity": sens, "checklist": checklist,
        "contributions": contributions, "rejected": res["rejected_summary"],
        "notes": res["notes"], "equity": equity, "orders": orders,
        "positions": res["positions"], "signals": res["signals"],
        "trade_days": res["trade_days"],
    }
    if persist:
        persist_run(store, out)
    return out


def cost_sensitivity(store, strategy_id, params, start, end, universe_size,
                     initial_capital, benchmark_code, ids, seed, train_end) -> dict:
    """FR-B-11：同一策略强制跑 0 / 5 / 10bp 三档滑点。"""
    base = settings.load().cost
    out = {}
    for bp in (0.0, 5.0, 10.0):
        cost = dict(base, slippage_bp=bp)
        r = backtest(store, strategy_id, params, start, end, universe_size, cost,
                     initial_capital, benchmark_code, ids, seed, train_end,
                     persist=False, sensitivity=False)
        out[f"{bp:g}bp"] = {
            "年化收益": r["metrics"]["收益"]["年化收益"],
            "Sharpe": r["metrics"]["比值"]["Sharpe"],
            "最大回撤": r["metrics"]["风险"]["max_drawdown"],
            "成本占毛收益": r["metrics"]["交易"].get("成本占毛收益"),
        }
    return out


def run_checklist(m_full: dict, m_in: dict, m_oos: dict, sens: dict,
                  equity: pd.DataFrame) -> dict:
    """过拟合体检表（FR-A-04 红线）。"""
    sh_in = m_in["比值"]["Sharpe"]
    sh_oos = m_oos["比值"]["Sharpe"]
    rows = []
    ok_in = sh_oos is not None and sh_oos >= 0.3 and (sh_in in (None, 0) or sh_oos >= 0.3 * sh_in)
    rows.append({"项": "样本外 Sharpe", "阈值": "≥0.3 且 ≥0.3×样本内",
                 "本例": f"{sh_oos} / {sh_in}", "判定": "pass" if ok_in else "FAIL"})
    ratios = [v["成本占毛收益"] for v in sens.values() if v.get("成本占毛收益") is not None]
    worst = max(ratios) if ratios else None
    ok_cost = worst is None or worst <= 0.40
    rows.append({"项": "成本占毛收益", "阈值": "≤40%",
                 "本例": worst if worst is not None else "未跑敏感性（--fast）",
                 "判定": "pass" if ok_cost else "FAIL"})
    ann = [v["年化收益"] for v in sens.values()]
    mono = all(ann[i] >= ann[i + 1] - 1e-9 for i in range(len(ann) - 1)) if len(ann) > 1 else True
    rows.append({"项": "滑点敏感性单调", "阈值": "随滑点不升高", "本例": mono,
                 "判定": "pass" if mono else "WARN"})
    sign_flip = any(v["Sharpe"] is not None and v["Sharpe"] < 0 for v in sens.values())
    rows.append({"项": "成本扰动符号", "阈值": "不翻转", "本例": "翻转" if sign_flip else "稳定",
                 "判定": "WARN" if sign_flip else "pass"})
    dd = m_full["风险"]["max_drawdown"]
    rows.append({"项": "最大回撤", "阈值": "≥-35%", "本例": dd,
                 "判定": "pass" if dd is not None and dd >= -0.35 else "FAIL"})
    status = "FAIL" if any(r["判定"] == "FAIL" for r in rows) else "pass"
    return {"rows": rows, "status": status}


def symbol_contributions(orders: pd.DataFrame, positions: pd.DataFrame,
                         panels: Panels) -> dict:
    if orders.empty:
        return {"top": [], "bottom": []}
    realized = orders.groupby("symbol").apply(
        lambda g: float(g.loc[g["side"] == "SELL", "gross"].sum()
                        - g.loc[g["side"] == "BUY", "gross"].sum()
                        - g["fee"].sum()), include_groups=False).sort_values()
    top = [(s, round(v, 2)) for s, v in realized.tail(10).iloc[::-1].items()]
    bottom = [(s, round(v, 2)) for s, v in realized.head(10).items()]
    return {"top": top, "bottom": bottom, "traded_symbols": int(len(realized))}


def persist_run(store: DuckDBStore, out: dict) -> None:
    store.create_run({
        "run_id": out["run_id"], "strategy_id": out["config"]["strategy_id"],
        "version": out["config"]["version"], "start_date": out["config"]["start"],
        "end_date": out["config"]["end"], "universe": out["config"]["universe"],
        "initial_capital": out["config"]["initial_capital"],
        "cost_model": json.dumps(out["config"]["cost"]), "benchmark": out["config"]["benchmark"],
        "config_hash": out["config_hash"], "seed": out["config"]["seed"],
        "data_version": out["data_version"], "status": "succeeded", "error": None,
        "lookahead_status": out["lookahead"]["lookahead_status"],
        "metrics": json.dumps({"full": out["metrics"], "in": out["metrics_in_sample"],
                               "oos": out["metrics_oos"], "sensitivity": out["cost_sensitivity"],
                               "elapsed_sec": out["elapsed_sec"]}, ensure_ascii=False, default=str),
        "checklist": json.dumps(out["checklist"], ensure_ascii=False, default=str),
        "created_at": pd.Timestamp.now(), "finished_at": pd.Timestamp.now(),
    })
    eq = out["equity"].reset_index()
    eq["run_id"] = out["run_id"]
    store.save_equity(eq[["run_id", "ts", "nav", "cash", "mv", "exposure", "turnover", "fee"]])
    if not out["orders"].empty:
        od = out["orders"].copy()
        od["run_id"] = out["run_id"]
        store.save_orders(od)
    if len(out["positions"]):
        ps = out["positions"].reset_index(drop=True).copy()
        ps["run_id"] = out["run_id"]
        ps["adj_cost"] = ps["cost"]
        store.save_positions(ps[["run_id", "ts", "symbol", "qty", "sellable_qty",
                                "cost", "adj_cost", "mv", "weight"]])
