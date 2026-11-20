"""quant CLI（DETAILED-DESIGN §20）。与后续 API 共用 core.services，不绕 HTTP。"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import typer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.config import settings  # noqa: E402
from core.store.duckdb_store import DuckDBStore  # noqa: E402

app = typer.Typer(help="quant-pro 智能量化系统 CLI", no_args_is_help=True)


def _store(db: str | None = None) -> DuckDBStore:
    st = settings.load()
    return DuckDBStore(db or st["DB_PATH"])


@app.command()
def status(db: str = typer.Option(None)):
    """数据水位与自检：行数、最新交易日、issue、作业、密钥状态。"""
    s = settings.load()
    store = _store(db)
    latest = store.latest_trade_date()
    typer.echo(f"store          : DuckDB {s['DB_PATH']}")
    typer.echo(f"标的           : {store.scalar('SELECT count(*) FROM instrument')}")
    typer.echo(f"日历交易日     : {store.scalar('SELECT count(*) FROM trade_calendar')}")
    typer.echo(f"行情行数       : {store.bar_count():,}")
    typer.echo(f"最新交易日     : {latest}")
    typer.echo(f"因子行数       : {store.scalar('SELECT count(*) FROM factor_value'):,}")
    typer.echo(f"回测运行       : {store.scalar('SELECT count(*) FROM backtest_run')}")
    typer.echo(f"数据 issue     : {store.issue_count()}（阻断 "
               f"{len(store.list_issues(blocking_only=True, limit=100000))}）")
    typer.echo(f"密钥           : {sorted(s.secrets)}  目录 {settings.SECRETS_DIR}")
    for w in s.warnings:
        typer.echo(f"[warn] {w}")


@app.command()
def fetch(start: str = "2016-01-04", end: str = "2025-12-31",
          rate: float = 6.0, db: str = typer.Option(None)):
    """全量/增量抓取（断点续传，重复执行只补缺口）。"""
    from core.jobs.fetch import bootstrap
    out = bootstrap(date.fromisoformat(start), date.fromisoformat(end),
                    db_path=_store(db).path, rate=rate)
    typer.echo(json.dumps(out, ensure_ascii=False, default=str, indent=2))


@app.command()
def quality(start: str = "2016-01-04", end: str = "2025-12-31",
            min_coverage: int = 100, db: str = typer.Option(None)):
    """重跑数据质量校验并输出分布。"""
    from core.jobs.fetch import run_quality
    out = run_quality(_store(db), date.fromisoformat(start), date.fromisoformat(end),
                      min_coverage=min_coverage)
    typer.echo(json.dumps(out, ensure_ascii=False, default=str, indent=2))


@app.command()
def factor(db: str = typer.Option(None), start: str = "2016-01-04", end: str = "2025-12-31",
           universe_size: int = 1000, ids: str = ""):
    """计算并落库因子（流动性样本池）。"""
    from core.services import candidate_symbols, compute_factors
    from core.engine.panels import load
    store = _store(db)
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    cands = candidate_symbols(store, s, n=max(universe_size * 3, 1500))
    panels = load(store, s, e, symbols=cands)
    picked = [i for i in ids.split(",") if i] or None
    from core.factor.registry import REGISTRY
    got = compute_factors(store, panels, picked or list(REGISTRY))
    typer.echo(f"因子 {len(got)} 个已落库：{list(got)}；面板 "
               f"{len(panels.days)}日 × {len(panels.symbols)}只，"
               f"{panels.memory_mb()} MB")


@app.command()
def evaluate(factor_id: str, horizon: int = 20, universe_size: int = 1000,
             start: str = "2016-01-04", end: str = "2025-12-31", db: str = typer.Option(None)):
    """因子评估：IC / ICIR / 分层收益 / 相关性。"""
    from core.engine.panels import load
    from core.factor.evaluate import evaluate as ev, max_correlation
    from core.factor.registry import REGISTRY
    from core.factor.standardize import standardize
    from core.services import candidate_symbols, compute_factors
    store = _store(db)
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    panels = load(store, s, e, symbols=candidate_symbols(store, s, n=universe_size * 3))
    factors = compute_factors(store, panels, list(REGISTRY), persist=False)
    raw = REGISTRY[factor_id].fn(panels)
    std, _ = standardize(raw, REGISTRY[factor_id].direction)
    others = {k: v for k, v in factors.items() if k != factor_id}
    corr_id, corr = max_correlation(std.reindex(panels.days), others)
    res = ev(std.reindex(panels.days), panels.adj_close, horizon)
    res["max_corr"] = {"with": corr_id, "value": round(corr, 4)}
    typer.echo(json.dumps(res, ensure_ascii=False, indent=2, default=str))


@app.command()
def backtest(strategy_id: str = "s2_multifactor", top_n: int = 30,
             start: str = "2016-01-04", end: str = "2025-12-31",
             train_end: str = "2021-12-31", universe_size: int = 1000,
             initial_capital: float = 1_000_000.0, slippage_bp: float = 5.0,
             no_sensitivity: bool = False, db: str = typer.Option(None),
             out_dir: str = ""):
    """跑回测：指标 + 未来函数门禁 + 成本敏感性 + 体检表 + 报告。"""
    from core.services import backtest as run
    st = settings.load()
    params = {"top_n": top_n, "constraints": dict(st.constraints)}
    if strategy_id == "s2_multifactor":
        params["factors"] = {"mom_20": .25, "mom_60": .15, "vol_60": .15,
                             "size_float": .15, "turnover_20": .15, "amihud_20": .15}
    res = run(_store(db), strategy_id, params, date.fromisoformat(start),
              date.fromisoformat(end), universe_size,
              dict(st.cost, slippage_bp=slippage_bp), initial_capital,
              st["BENCHMARK"], seed=7, train_end=date.fromisoformat(train_end),
              sensitivity=not no_sensitivity)
    _print_summary(res)
    if out_dir or True:
        from core.performance.report import write_report
        base = settings.REPORT_DIR
        path = write_report(res, base, initial_capital)
        typer.echo(f"报告：{path}")
    return res


def _print_summary(res: dict) -> None:
    m = res["metrics"]
    typer.echo(f"\nrun_id={res['run_id']}  config_hash={res['config_hash']}  "
               f"耗时={res['elapsed_sec']}s  面板={res['panels']}")
    typer.echo(f"数据版本={res['data_version']}  交易日={res['trade_days']}")
    for grp in ("收益", "风险", "比值", "交易"):
        typer.echo(f"[{grp}] " + json.dumps(m[grp], ensure_ascii=False, default=str))
    typer.echo("样本内 " + json.dumps({k: res["metrics_in_sample"]["比值"][k]
                                    for k in ("Sharpe", "Calmar")}, ensure_ascii=False))
    typer.echo("样本外 " + json.dumps({**{k: res["metrics_oos"]["比值"][k]
                                       for k in ("Sharpe", "Calmar")},
                                       **res["metrics_oos"]["收益"]}, ensure_ascii=False))
    typer.echo("成本敏感性 " + json.dumps(res["cost_sensitivity"], ensure_ascii=False,
                                       default=str))
    typer.echo("未来函数门禁 " + res["lookahead"]["lookahead_status"])
    for c in res["lookahead"]["checks"]:
        typer.echo(f"  - {c['lag']} {c['name']}: {c['status']} | {c['detail']}")
    typer.echo("体检表 " + res["checklist"]["status"])
    for r in res["checklist"]["rows"]:
        typer.echo(f"  - {r['项']}: {r['判定']} (阈值 {r['阈值']}, 本例 {r['本例']})")
    typer.echo(f"拒单分布 {res['rejected']}  备注 {len(res['notes'])} 条")


@app.command()
def runs(limit: int = 20, db: str = typer.Option(None)):
    """列出历史回测。"""
    typer.echo(_store(db).list_runs(limit).to_string())


@app.command()
def report(run_id: str, db: str = typer.Option(None)):
    """从库中重建报告（离线单文件 HTML）。"""
    store = _store(db)
    rec = store.get_run(run_id)
    typer.echo(json.dumps({k: rec[k] for k in ("run_id", "status", "lookahead_status",
                                           "config_hash", "metrics")},
                          ensure_ascii=False, indent=2, default=str))
    typer.echo(f"equity 行数={len(store.load_equity(run_id))} "
               f"orders={len(store.load_orders(run_id))}")


@app.command()
def selftest(db: str = typer.Option(None)):
    """口径自检：复权/整手/涨跌停/现金恒等式抽样断言（交付前必跑）。"""
    from core.selftest import run_all
    typer.echo(json.dumps(run_all(_store(db)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    app()
