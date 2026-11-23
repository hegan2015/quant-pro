"""quant-pro API（P2 服务化）。/api/** 全量 Bearer 门禁，仅 /healthz 例外。

运行：.venv/bin/python -m uvicorn app.api.main:app --port 8102
控制台：scripts/serve_console.py（8101，同源策略见 CORS 白名单）
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api import auth
from core.config import settings
from core.paper import service as paper
from core.risk import engine as risk
from core.signal import service as sig
from core.store.duckdb_store import DuckDBStore

app = FastAPI(title="quant-pro API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8101", "http://localhost:8101"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def seed_reference_data() -> None:
    """启动即幂等初始化参考数据：内置风控规则 + 因子元数据。

    否则新库首次打开控制台时「风控规则」「因子库」是空表，看起来像没有数据。
    """
    from core.risk.engine import ensure_rules
    from core.factor.registry import meta_frame
    st = store()
    ensure_rules(st)
    st.upsert_factor_meta(meta_frame())


_STORE: DuckDBStore | None = None


def store() -> DuckDBStore:
    """进程内单连接：DuckDB 同进程同文件不允许多连接，并发靠 cursor 隔离。"""
    global _STORE
    if _STORE is None:
        _STORE = DuckDBStore(settings.load()["DB_PATH"])
    return _STORE


def _df(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", date_format="iso", force_ascii=False))


@app.exception_handler(sig.PublishBlocked)
async def publish_blocked(_, exc: sig.PublishBlocked):
    return JSONResponse(status_code=422, content={"code": "QUANT-S-001",
                                                 "reasons": exc.reasons})


@app.exception_handler(KeyError)
async def not_found(_, exc: KeyError):
    return JSONResponse(status_code=404, content={"code": "QUANT-404", "message": str(exc)})


@app.exception_handler(ValueError)
async def bad_request(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"code": "QUANT-400", "message": str(exc)})


@app.get("/healthz")
def healthz():
    st = store()
    return {"status": "ok", "store_mode": "duckdb", "latest_trade_date": str(st.latest_trade_date()),
            "bars": st.bar_count()}


@app.get("/api/indices")
def indices(p=Depends(auth.principal)):
    """指数快照：最新点位 + 日涨跌（用最近两个有行情的交易日），供顶栏行情条。"""
    st = store()
    end = st.latest_trade_date()
    start = end.replace(year=end.year - 1) if end else None
    if start is None:
        return []
    rows = st.query(
        "SELECT index_code, ts, close FROM index_bar WHERE ts BETWEEN ? AND ?"
        " ORDER BY index_code, ts", [start, end])
    by: dict[str, list] = {}
    for code, ts, close in rows:
        by.setdefault(code, []).append((ts, float(close)))
    names = {"000300": "沪深300", "000905": "中证500", "000852": "中证1000",
             "000001": "上证指数", "399006": "创业板指", "399001": "深证成指"}
    out = []
    for code, series in sorted(by.items()):
        last = series[-1]
        prev = series[-2][1] if len(series) > 1 else last[1]
        out.append({"index_code": code, "name": names.get(code, code),
                    "ts": str(last[0]), "close": round(last[1], 2),
                    "chg": round(last[1] / prev - 1.0, 6) if prev else 0.0})
    return out


@app.get("/api/status")
def status(p=Depends(auth.principal)):
    st = store()
    return {"latest_trade_date": str(st.latest_trade_date()), "bars": st.bar_count(),
            "store_mode": "duckdb（进程内）",
            "instruments": int(st.scalar("SELECT count(*) FROM instrument")),
            "factors": int(st.scalar("SELECT count(*) FROM factor_value")),
            "runs": int(st.scalar("SELECT count(*) FROM backtest_run")),
            "signals": int(st.scalar("SELECT count(*) FROM signal_run")),
            "accounts": int(st.scalar("SELECT count(*) FROM paper_account")),
            "open_risk_events": int(st.scalar(
                "SELECT count(*) FROM risk_event WHERE status='open'")),
            "data_version": st.data_version(date(2016, 1, 4), st.latest_trade_date())
            if st.bar_count() else None,
            "breaker_open": risk.circuit_breaker_open(st),
            "user": p["user"], "roles": p["roles"]}


@app.get("/api/instruments")
def instruments(as_of: str | None = None, p=Depends(auth.principal)):
    st = store()
    d = date.fromisoformat(as_of) if as_of else st.latest_trade_date()
    return _df(st.universe(d))


@app.get("/api/bars")
def bars(start: str, end: str, symbol: str | None = None, limit: int = 500,
         p=Depends(auth.principal)):
    st = store()
    where, args = "ts BETWEEN ? AND ?", [date.fromisoformat(start), date.fromisoformat(end)]
    if symbol:
        where += " AND symbol = ?"
        args.append(symbol)
    df = st.query_df(f"SELECT * FROM daily_bar WHERE {where} ORDER BY ts, symbol LIMIT ?",
                     args + [limit])
    return _df(df)


@app.get("/api/data/issues")
def issues(blocking: bool = False, limit: int = 200, p=Depends(auth.principal)):
    return _df(store().list_issues(blocking_only=blocking, limit=limit))


class Amendment(BaseModel):
    ts: str
    symbol: str
    field: str
    new_value: str
    reason: str


@app.post("/api/data/amendments", status_code=201)
def amend(body: Amendment, p=Depends(auth.principal)):
    auth.require(p, "data")
    st = store()
    old = st.scalar("SELECT CAST(? AS VARCHAR) FROM daily_bar WHERE ts=? AND symbol=?",
                    [body.field, date.fromisoformat(body.ts), body.symbol])
    base = int(st.scalar("SELECT coalesce(max(id),0) FROM data_amendment") or 0)
    st.amend({"id": base + 1, "ts": date.fromisoformat(body.ts), "symbol": body.symbol,
              "field": body.field, "old_value": str(old), "new_value": body.new_value,
              "reason": body.reason, "actor": p["user"]})
    return {"id": base + 1, "old_value": str(old), "stale_marked": True}


@app.get("/api/jobs")
def jobs(trade_date: str | None = None, p=Depends(auth.principal)):
    st = store()
    return _df(st.job_status(date.fromisoformat(trade_date) if trade_date else None))


@app.post("/api/jobs/{job_id}/run")
def run_job(job_id: str, trade_date: str | None = None, p=Depends(auth.principal)):
    auth.require(p, "data", "researcher")
    from core.jobs.fetch import run_quality
    st = store()
    d = date.fromisoformat(trade_date) if trade_date else st.latest_trade_date()
    if job_id == "quality_check":
        return run_quality(st, d, d)
    raise HTTPException(400, f"未知作业：{job_id}")


@app.get("/api/factors")
def factors(p=Depends(auth.principal)):
    st = store()
    meta = st.factor_meta()
    out = []
    for r in meta.itertuples():
        ev = st.query_df("SELECT * FROM factor_eval_snapshot WHERE factor_id=?", [r.factor_id])
        out.append({"factor_id": r.factor_id, "name": r.name, "direction": int(r.direction),
                    "eval": _df(ev)})
    return out


@app.post("/api/factors/{factor_id}/evaluate")
def evaluate_factor(factor_id: str, horizon: int = 20, p=Depends(auth.principal)):
    auth.require(p, "researcher")
    from core.factor.evaluate import evaluate as ev
    from core.factor.registry import REGISTRY, compute
    from core.factor.standardize import standardize
    from core.engine.panels import load
    from core.services import candidate_symbols
    st = store()
    end = st.latest_trade_date()
    start = date(end.year - 3, end.month, end.day)
    panels = load(st, start, end, symbols=candidate_symbols(st, start, n=1500))
    f = standardize(compute(factor_id, panels), REGISTRY[factor_id].direction, min_n=50)[0]
    res = ev(f.reindex(panels.days), panels.adj_close, horizon)
    st.upsert_factor_eval(factor_id, f"{horizon}d", res)
    return res


@app.get("/api/strategies")
def strategies(p=Depends(auth.principal)):
    from core.strategy.builtin import STRATEGIES
    return [{"strategy_id": k, "version": v.version, "params": v().params()}
            for k, v in STRATEGIES.items()]


class BacktestReq(BaseModel):
    strategy_id: str = "s2_multifactor"
    params: dict = {}
    start: str = "2016-01-04"
    end: str = "2025-12-31"
    train_end: str = "2021-12-31"
    universe_size: int = 1000
    initial_capital: float = 10_000_000.0
    sensitivity: bool = False


@app.post("/api/backtests")
def create_backtest(body: BacktestReq, p=Depends(auth.principal)):
    auth.require(p, "researcher", "pm")
    from core.services import backtest
    st = store()
    res = backtest(st, body.strategy_id, body.params, date.fromisoformat(body.start),
                   date.fromisoformat(body.end), body.universe_size,
                   initial_capital=body.initial_capital, sensitivity=body.sensitivity,
                   train_end=date.fromisoformat(body.train_end))
    return {"run_id": res["run_id"], "config_hash": res["config_hash"],
            "lookahead_status": res["lookahead"]["lookahead_status"],
            "checklist_status": res["checklist"]["status"],
            "metrics": res["metrics"], "elapsed_sec": res["elapsed_sec"]}


@app.get("/api/backtests")
def list_backtests(limit: int = 30, p=Depends(auth.principal)):
    return _df(store().list_runs(limit))


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str, p=Depends(auth.principal)):
    rec = store().get_run(run_id)
    return {k: rec[k] for k in ("run_id", "strategy_id", "status", "lookahead_status",
                                "config_hash", "data_version", "metrics", "checklist")}


@app.get("/api/backtests/{run_id}/equity")
def backtest_equity(run_id: str, p=Depends(auth.principal)):
    """净值序列 + 基准净值：benchmark_nav 不落库，按该 run 的基准指数即时重算。"""
    st = store()
    df = st.load_equity(run_id)
    if df.empty:
        return []
    code = st.get_run(run_id).get("benchmark") or "000300"
    rows = st.query(
        "SELECT ts, close FROM index_bar WHERE index_code = ? AND ts BETWEEN ? AND ?"
        " ORDER BY ts", [code, df.ts.min(), df.ts.max()])
    if rows:
        idx = pd.Series([r[1] for r in rows],
                        index=[r[0].date() if hasattr(r[0], "date") else r[0] for r in rows])
        bnav = (1.0 + idx.pct_change().fillna(0.0)).cumprod()
        df["benchmark_nav"] = bnav.reindex(df.ts).ffill().bfill().to_numpy()
        df["benchmark_name"] = code
    return _df(df)


@app.get("/api/backtests/{run_id}/orders")
def backtest_orders(run_id: str, status: str | None = None, p=Depends(auth.principal)):
    df = store().load_orders(run_id)
    if status:
        df = df[df.status == status]
    return _df(df)


@app.get("/api/backtests/{run_id}/report")
def backtest_report(run_id: str, p=Depends(auth.principal)):
    path = settings.REPORT_DIR / f"backtest-{run_id}-{date.today():%Y%m%d}.html"
    if not path.exists():
        cands = sorted(settings.REPORT_DIR.glob(f"backtest-{run_id}-*.html"))
        if not cands:
            raise HTTPException(404, "报告不存在")
        path = cands[-1]
    return FileResponse(path, media_type="text/html")


class SignalReq(BaseModel):
    strategy_id: str = "s2_multifactor"
    params: dict = {}
    trade_date: str
    account_id: str | None = None


@app.get("/api/signals")
def list_signals(trade_date: str | None = None, p=Depends(auth.principal)):
    st = store()
    return _df(st.list_signals(date.fromisoformat(trade_date) if trade_date else None))


@app.post("/api/signals", status_code=201)
def create_signal(body: SignalReq, p=Depends(auth.principal)):
    auth.require(p, "researcher", "pm")
    return sig.build_signal(store(), body.strategy_id, body.params,
                            date.fromisoformat(body.trade_date), actor=p["user"],
                            account_id=body.account_id)


@app.get("/api/signals/{run_id}")
def get_signal(run_id: str, p=Depends(auth.principal)):
    st = store()
    rec = st.get_signal(run_id)
    rec["items"] = _df(st.signal_items(run_id))
    return rec


class PublishReq(BaseModel):
    confirm: bool = False


@app.post("/api/signals/{run_id}/publish")
def publish_signal(run_id: str, body: PublishReq, p=Depends(auth.principal)):
    auth.require(p, "pm")
    return sig.publish(store(), run_id, p["user"], confirm=body.confirm)


class WithdrawReq(BaseModel):
    reason: str


@app.post("/api/signals/{run_id}/withdraw")
def withdraw_signal(run_id: str, body: WithdrawReq, p=Depends(auth.principal)):
    auth.require(p, "pm")
    return sig.withdraw(store(), run_id, p["user"], body.reason)


class AccountReq(BaseModel):
    name: str
    initial_capital: float = 10_000_000.0
    strategy_id: str = "s2_multifactor"
    start_date: str


@app.get("/api/paper/accounts")
def list_accounts(p=Depends(auth.principal)):
    return _df(store().list_paper_accounts())


@app.post("/api/paper/accounts", status_code=201)
def create_account(body: AccountReq, p=Depends(auth.principal)):
    auth.require(p, "pm")
    aid = paper.create_account(store(), body.name, body.initial_capital, body.strategy_id,
                               date.fromisoformat(body.start_date))
    return {"account_id": aid}


@app.get("/api/paper/accounts/{account_id}/positions")
def positions(account_id: str, ts: str | None = None, p=Depends(auth.principal)):
    return _df(store().paper_positions(account_id, date.fromisoformat(ts) if ts else None))


@app.get("/api/paper/accounts/{account_id}/orders")
def paper_orders(account_id: str, p=Depends(auth.principal)):
    return _df(store().paper_orders(account_id))


@app.get("/api/paper/accounts/{account_id}/equity")
def paper_equity(account_id: str, p=Depends(auth.principal)):
    return _df(store().paper_equity(account_id))


@app.get("/api/paper/accounts/{account_id}/ledger")
def paper_ledger(account_id: str, p=Depends(auth.principal)):
    return _df(store().paper_ledger(account_id))


@app.get("/api/paper/accounts/{account_id}/reconciliation")
def reconciliation(account_id: str, p=Depends(auth.principal)):
    return _df(store().recon(account_id))


class SettleReq(BaseModel):
    upto: str


@app.post("/api/paper/accounts/{account_id}/settle")
def settle(account_id: str, body: SettleReq, p=Depends(auth.principal)):
    auth.require(p, "pm")
    return paper.settle(store(), account_id, date.fromisoformat(body.upto))


class ReplayReq(BaseModel):
    from_date: str


@app.post("/api/paper/accounts/{account_id}/replay", status_code=201)
def replay(account_id: str, body: ReplayReq, p=Depends(auth.principal)):
    auth.require(p, "pm")
    return {"account_id": paper.replay(store(), account_id, date.fromisoformat(body.from_date))}


@app.get("/api/risk/rules")
def risk_rules(p=Depends(auth.principal)):
    return [r.__dict__ for r in store().load_rules()]


class RuleUpdate(BaseModel):
    threshold: float | None = None
    enabled: bool | None = None
    reason: str


@app.put("/api/risk/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate, p=Depends(auth.principal)):
    auth.require(p, "risk")
    st = store()
    rules = {r.rule_id: r for r in st.load_rules()}
    if rule_id not in rules:
        raise KeyError(rule_id)
    r = rules[rule_id]
    before = {"threshold": r.threshold, "enabled": r.enabled}
    if body.threshold is not None:
        r.threshold = body.threshold
    if body.enabled is not None:
        r.enabled = body.enabled
    r.version += 1
    st.upsert_rules(pd.DataFrame([r.__dict__]))
    st.execute("INSERT INTO app_config VALUES (?,?,?,?)",
               [f"risk_rule:{rule_id}", json.dumps({"before": before, "after": r.__dict__,
                                                   "reason": body.reason}, ensure_ascii=False),
                pd.Timestamp.now(), p["user"]])
    return r.__dict__


@app.get("/api/risk/events")
def risk_events(status: str | None = None, p=Depends(auth.principal)):
    return _df(store().list_risk_events(status))


class AckReq(BaseModel):
    reason: str


@app.post("/api/risk/events/{event_id}/ack")
def ack_event(event_id: int, body: AckReq, p=Depends(auth.principal)):
    auth.require(p, "risk")
    store().ack_risk_event(event_id, p["user"], body.reason)
    return {"id": event_id, "status": "acked", "by": p["user"]}


@app.get("/api/risk/breaker")
def breaker(p=Depends(auth.principal)):
    st = store()
    return {"open": risk.circuit_breaker_open(st),
            "open_events": _df(st.list_risk_events(status="open"))}


# ---------------------------------------------------------------------------
# 控制台静态资源同源提供（ops 运维台单端口即可打开界面）。
# 必须挂在所有 /api 路由之后：Starlette 按注册顺序匹配，挂载 "/" 在前会
# 把后定义的路由全部遮蔽成 404（曾因此导致信号/模拟盘/风控页「没有数据」）。
CONSOLE_DIR = settings.ROOT / "app" / "console"
if CONSOLE_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(CONSOLE_DIR), html=True), name="console")
