"""DuckDB 存储实现（P1 运行态）。

口径纪律：
- 行情以原始价为准，连续价 = 原始价 × adj_factor，由本层统一计算（AP-01）；
- 写入只走 upsert（幂等，FR-D-02/FR-O-02），修正另记 data_amendment（ADR-013）；
- data_version 绑定「行数 + 抓取时间上界 + 抽样校验和」，供回测可复现使用（FR-B-12）。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import date, datetime

import duckdb
import pandas as pd

def _iso(d: date) -> str:
    """DDL 内联日期前的类型校验：只接受 date/datetime，杜绝字符串注入面。"""
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    raise TypeError(f"日期参数必须为 date/datetime，收到 {type(d)}")


BAR_FIELDS = ["open", "high", "low", "close", "pre_close", "volume", "amount",
              "adj_factor", "limit_up", "limit_down", "is_suspended", "is_final"]


class DuckDBStore:
    # DuckDB 同进程同文件单连接；并发请求必须串行化（cursor 仍共享连接锁）
    _lock = threading.RLock()

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.con = duckdb.connect(path)
        self.init_schema()

    # ---------------------------------------------------------------- 取数封装
    def query(self, sql: str, args: list | None = None) -> list[tuple]:
        """每操作独立 cursor + 进程锁：同进程同文件单连接，并发请求串行化。"""
        with self._lock:
            cur = self.con.cursor()
            try:
                return cur.execute(sql, args or []).fetchall()
            finally:
                cur.close()

    def query_df(self, sql: str, args: list | None = None) -> pd.DataFrame:
        with self._lock:
            cur = self.con.cursor()
            try:
                return cur.execute(sql, args or []).fetchdf()
            finally:
                cur.close()

    def query_df_with(self, name: str, df: pd.DataFrame, sql: str) -> pd.DataFrame:
        """在同一 cursor 内注册临时关系并查询（父连接注册对 cursor 不可见）。"""
        with self._lock:
            cur = self.con.cursor()
            try:
                cur.register(name, df)
                return cur.execute(sql).fetchdf()
            finally:
                cur.unregister(name)
                cur.close()

    def scalar(self, sql: str, args: list | None = None):
        rows = self.query(sql, args)
        return rows[0][0] if rows and rows[0] else None

    def execute(self, sql: str, args: list | None = None) -> None:
        with self._lock:
            cur = self.con.cursor()
            try:
                cur.execute(sql, args or []).fetchall()
            finally:
                cur.close()

    # ---------------------------------------------------------------- 基础设施
    def init_schema(self) -> None:
        ddl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.duckdb.sql")
        self.execute(open(ddl, encoding="utf-8").read())

    def close(self) -> None:
        self.con.close()

    def _upsert(self, table: str, df: pd.DataFrame, conflict: list[str] | None = None) -> int:
        if df is None or df.empty:
            return 0
        cols = ", ".join(df.columns)
        if conflict:
            # 表存在多个唯一约束时（如 job_run），INSERT OR REPLACE 无法判定冲突目标
            sets = ", ".join(f"{c} = excluded.{c}" for c in df.columns if c not in conflict)
            sql = (f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _src "
                   f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {sets}")
        else:
            sql = f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _src"
        with self._lock:
            cur = self.con.cursor()
            try:
                cur.register("_src", df)
                cur.execute(sql).fetchall()
            finally:
                cur.unregister("_src")
                cur.close()
        return len(df)

    # ---------------------------------------------------------------- 主数据
    def upsert_instruments(self, df: pd.DataFrame) -> int:
        return self._upsert("instrument", df)

    def instruments(self) -> pd.DataFrame:
        return self.query_df("SELECT * FROM instrument")

    def universe(self, as_of: date) -> pd.DataFrame:
        """按历史日期回溯当日在市标的（含此后退市者），抗幸存者偏差（FR-D-01）。"""
        return self.query_df(
            """SELECT * FROM instrument
               WHERE list_date <= ?
                 AND (delist_date IS NULL OR delist_date > ?)""",
            [as_of, as_of],
        )

    # ---------------------------------------------------------------- 日历
    def upsert_calendar(self, days: list[date]) -> int:
        df = pd.DataFrame({"trade_date": list(days), "is_open": [True] * len(days)})
        return self._upsert("trade_calendar", df)

    def trade_days(self, start: date, end: date) -> list[date]:
        rows = self.query(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date BETWEEN ? AND ? "
            "ORDER BY trade_date", [start, end],
        )
        if not rows:
            raise CalendarError(f"交易日历缺失区间 {start}..{end}（FR-D-06：不得静默跳过）")
        return [r[0].date() if isinstance(r[0], datetime) else r[0] for r in rows]

    # ---------------------------------------------------------------- 行情
    def upsert_bars(self, df: pd.DataFrame) -> int:
        return self._upsert("daily_bar", df)

    def upsert_index_bars(self, df: pd.DataFrame) -> int:
        return self._upsert("index_bar", df)

    def load_bars(self, start: date, end: date, symbols: list[str] | None = None,
                  fields: list[str] | None = None, with_adj: bool = True) -> pd.DataFrame:
        fields = fields or BAR_FIELDS
        sel = ", ".join(["ts", "symbol"] + fields)
        where = "ts BETWEEN ? AND ?"
        args: list = [start, end]
        with self._lock:
            cur = self.con.cursor()
            try:
                if symbols:
                    cur.register("_sym", pd.DataFrame({"symbol": list(symbols)}))
                    where += " AND symbol IN (SELECT symbol FROM _sym)"
                df = cur.execute(
                    f"SELECT {sel} FROM daily_bar WHERE {where} ORDER BY ts, symbol", args).fetchdf()
            finally:
                if symbols:
                    cur.unregister("_sym")
                cur.close()
        if with_adj and "close" in df and "adj_factor" in df:
            for f in ("open", "high", "low", "close", "pre_close"):
                if f in df:
                    df["adj_" + f] = df[f] * df["adj_factor"]
        return df

    def pivot(self, start: date, end: date, field: str, symbols: list[str] | None = None) -> pd.DataFrame:
        """宽表：index=ts, columns=symbol。adj_* 走连续价（原始价 × adj_factor）。"""
        col, expr = field, field
        if field.startswith("adj_"):
            col, expr = "adjv", f"({field[4:]} * adj_factor)"
        filt = f"ts BETWEEN DATE '{_iso(start)}' AND DATE '{_iso(end)}'"
        with self._lock:
            cur = self.con.cursor()
            try:
                if symbols:
                    cur.register("_sym", pd.DataFrame({"symbol": list(symbols)}))
                    filt += " AND symbol IN (SELECT symbol FROM _sym)"
                cur.execute("DROP VIEW IF EXISTS _p")
            # DDL 不支持 prepared 参数，日期在此处按 date 类型校验后内联（不接受字符串入参）
                cur.execute(f"CREATE TEMP VIEW _p AS SELECT ts, symbol, {expr} AS {col} "
                            f"FROM daily_bar WHERE {filt}")
                df = cur.execute(
                    f"PIVOT _p ON symbol USING any_value({col}) GROUP BY ts").fetchdf()
                cur.execute("DROP VIEW IF EXISTS _p")
            finally:
                if symbols:
                    cur.unregister("_sym")
                cur.close()
        df["ts"] = pd.to_datetime(df["ts"]).dt.date
        return df.set_index("ts").sort_index().sort_index(axis=1)

    def coverage(self, start: date, end: date) -> pd.DataFrame:
        return self.query_df(
            """SELECT ts, count(*) AS n, sum(CASE WHEN is_suspended THEN 1 ELSE 0 END) AS suspended
               FROM daily_bar WHERE ts BETWEEN ? AND ? GROUP BY ts ORDER BY ts""",
            [start, end])

    def latest_trade_date(self) -> date | None:
        r = self.scalar("SELECT max(ts) FROM daily_bar")
        return None if r is None else (r.date() if isinstance(r, datetime) else r)

    def bar_count(self, start: date | None = None, end: date | None = None) -> int:
        if start and end:
            return int(self.scalar(
                "SELECT count(*) FROM daily_bar WHERE ts BETWEEN ? AND ?", [start, end]))
        return int(self.scalar("SELECT count(*) FROM daily_bar"))

    def data_version(self, start: date, end: date) -> str:
        """数据水位指纹，用于回测可复现绑定（FR-B-12 / TC-B-15）。

        必须用整数聚合：浮点 sum 在并行归约下求和顺序不定，同样数据会算出不同哈希，
        导致 config_hash 抖动、重跑无法判定「同哈希必须同结果」。
        """
        rows = self.query(
            """SELECT count(*), max(ts), max(fetched_at),
                      sum(CAST(round(coalesce(close, 0) * 100) AS BIGINT)),
                      sum(CAST(round(coalesce(adj_factor, 0) * 1000000) AS BIGINT)),
                      sum(CAST(round(coalesce(volume, 0) / 100) AS BIGINT))
               FROM daily_bar WHERE ts BETWEEN ? AND ?""", [start, end])
        return hashlib.sha256("|".join(str(x) for x in rows[0]).encode()).hexdigest()[:12]

    # ---------------------------------------------------------------- 因子
    def upsert_factor_meta(self, df: pd.DataFrame) -> int:
        return self._upsert("factor_meta", df)

    def factor_meta(self) -> pd.DataFrame:
        return self.query_df("SELECT * FROM factor_meta")

    def write_factor(self, factor_id: str, wide: pd.DataFrame) -> int:
        long = wide.stack().reset_index()
        long.columns = ["ts", "symbol", "value"]
        long["factor_id"] = factor_id
        long = long[long["value"].notna()]
        return self._upsert("factor_value", long[["ts", "symbol", "factor_id", "value"]])

    def upsert_factor_eval(self, factor_id: str, window: str, res: dict) -> int:
        import json as _json
        row = {"factor_id": factor_id, "eval_window": window,
               "ic_mean": res.get("ic_mean"), "ic_std": res.get("ic_std"),
               "icir": res.get("icir"), "t_stat": res.get("t_stat"),
               "ic_pos_ratio": res.get("ic_pos_ratio"),
               "quantile_returns": _json.dumps(res.get("quantile_annualized")),
               "max_corr": (res.get("max_corr") or {}).get("value"),
               "calc_at": datetime.now()}
        return self._upsert("factor_eval_snapshot", pd.DataFrame([row]))

    def read_factor(self, factor_id: str, start: date | None = None,
                    end: date | None = None) -> pd.DataFrame:
        where, args = "factor_id = ?", [factor_id]
        if start and end:
            where += " AND ts BETWEEN ? AND ?"
            args += [start, end]
        df = self.query_df(f"SELECT ts, symbol, value FROM factor_value WHERE {where}", args)
        if df.empty:
            return df
        out = df.pivot(index="ts", columns="symbol", values="value")
        out.index = pd.to_datetime(out.index).date
        return out.sort_index().sort_index(axis=1)

    # ---------------------------------------------------------------- 回测产物
    def create_run(self, run: dict) -> None:
        self.execute(
            "INSERT OR REPLACE INTO backtest_run VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [run[k] for k in ("run_id", "strategy_id", "version", "start_date", "end_date",
                              "universe", "initial_capital", "cost_model", "benchmark",
                              "config_hash", "seed", "data_version", "status", "error",
                              "lookahead_status", "metrics", "checklist", "created_at",
                              "finished_at")],
        )

    def update_run(self, run_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE backtest_run SET {sets} WHERE run_id = ?",
                   [*fields.values(), run_id])

    def get_run(self, run_id: str) -> dict:
        df = self.query_df("SELECT * FROM backtest_run WHERE run_id = ?", [run_id])
        if df.empty:
            raise KeyError(f"run 不存在：{run_id}")
        rec = df.iloc[0].to_dict()
        for k in ("metrics", "checklist", "cost_model"):
            if isinstance(rec.get(k), str) and rec[k]:
                rec[k] = json.loads(rec[k])
        return rec

    def list_runs(self, limit: int = 50) -> pd.DataFrame:
        return self.query_df(
            "SELECT run_id, strategy_id, version, start_date, end_date, status,"
            " lookahead_status, config_hash, created_at FROM backtest_run"
            " ORDER BY created_at DESC LIMIT ?", [limit],
        )

    def save_orders(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        df = df.copy()
        df["order_id"] = range(1, len(df) + 1)
        return self._upsert("backtest_order", df[["order_id", "run_id", "ts", "exec_date",
                                                  "symbol", "side", "req_qty", "filled_qty",
                                                  "price", "gross", "fee", "status",
                                                  "reject_reason"]])

    def load_orders(self, run_id: str) -> pd.DataFrame:
        return self.query_df(
            "SELECT * FROM backtest_order WHERE run_id = ? ORDER BY exec_date, symbol", [run_id]
        )

    def save_equity(self, df: pd.DataFrame) -> int:
        return self._upsert("backtest_equity", df)

    def load_equity(self, run_id: str) -> pd.DataFrame:
        df = self.query_df(
            "SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY ts", [run_id]
        )
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"]).dt.date
        return df

    def save_positions(self, df: pd.DataFrame) -> int:
        return self._upsert("backtest_position", df)

    def load_positions(self, run_id: str, ts: date | None = None) -> pd.DataFrame:
        if ts:
            return self.query_df(
                "SELECT * FROM backtest_position WHERE run_id = ? AND ts = ? ORDER BY weight DESC",
                [run_id, ts],
            )
        return self.query_df(
            "SELECT * FROM backtest_position WHERE run_id = ? ORDER BY ts", [run_id]
        )

    def save_recon(self, df: pd.DataFrame) -> int:
        return self._upsert("recon_check", df)

    def load_recon(self, run_id: str) -> pd.DataFrame:
        return self.query_df(
            "SELECT * FROM recon_check WHERE run_id = ? ORDER BY ts", [run_id]
        )

    # ---------------------------------------------------------------- 质量与作业
    def clear_auto_issues(self, start: date, end: date, kinds: list[str]) -> int:
        """data_issue 是派生诊断表（可重生成），按窗口+类型清理后由校验作业重写。

        行情主数据不在此列：行情只追加、修正另记（ADR-013）。
        """
        before = int(self.scalar("SELECT count(*) FROM data_issue"))
        ph = ", ".join("?" for _ in kinds)
        self.execute(f"DELETE FROM data_issue WHERE ts BETWEEN ? AND ? AND kind IN ({ph})",
                     [start, end, *kinds])
        return before - int(self.scalar("SELECT count(*) FROM data_issue"))

    def write_issues(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        df = df.copy()
        base = int(self.scalar("SELECT coalesce(max(id),0) FROM data_issue") or 0)
        df["id"] = range(base + 1, base + 1 + len(df))
        if "status" not in df:
            df["status"] = "open"
        df["created_at"] = datetime.now()
        return self._upsert("data_issue", df[["id", "ts", "symbol", "field", "kind", "detail",
                                             "blocking", "status", "created_at"]])

    def list_issues(self, blocking_only: bool = False, limit: int = 200) -> pd.DataFrame:
        where = "blocking" if blocking_only else "TRUE"
        return self.query_df(
            f"SELECT * FROM data_issue WHERE {where} ORDER BY ts DESC LIMIT ?", [limit]
        )

    def issue_count(self, kind: str | None = None) -> int:
        if kind:
            return self.scalar(
                "SELECT count(*) FROM data_issue WHERE kind = ?", [kind])
        return self.scalar("SELECT count(*) FROM data_issue")

    def amend(self, rec: dict) -> None:
        """数据修正：原行保留，另记流水（FR-D-08）。"""
        self.execute(
            "INSERT INTO data_amendment VALUES (?,?,?,?,?,?,?,?,?,?)",
            [rec["id"], rec["ts"], rec["symbol"], rec["field"], rec["old_value"],
             rec["new_value"], rec["reason"], rec["actor"], rec.get("marked_stale", True),
             datetime.now()],
        )

    def job_start(self, job_id: str, trade_date: date, attempt: int, key: str) -> None:
        self._upsert("job_run", pd.DataFrame([{
            "job_id": job_id, "trade_date": trade_date, "attempt": attempt,
            "status": "running", "rows_affected": 0, "error": None,
            "started_at": datetime.now(), "finished_at": None, "idempotency_key": key,
        }]), conflict=["job_id", "trade_date", "attempt"])

    def job_finish(self, job_id: str, trade_date: date, attempt: int, status: str,
                   rows: int, error: str | None = None) -> None:
        self.execute(
            "UPDATE job_run SET status = ?, rows_affected = ?, error = ?, finished_at = ?"
            " WHERE job_id = ? AND trade_date = ? AND attempt = ?",
            [status, rows, error, datetime.now(), job_id, trade_date, attempt],
        )

    # ---------------------------------------------------------------- P2：风控
    def upsert_rules(self, df: pd.DataFrame) -> int:
        return self._upsert("risk_rule", df)

    def load_rules(self) -> list:
        from core.risk.engine import Rule
        rows = self.query_df("SELECT * FROM risk_rule ORDER BY priority")
        return [Rule(**{k: r[k] for k in ("rule_id", "name", "metric", "op", "threshold",
                                          "action", "priority", "enabled", "version", "scope")})
                for _, r in rows.iterrows()]

    def write_risk_events(self, trade_date: date, account_id: str, hits: list[dict]) -> int:
        base = int(self.scalar("SELECT coalesce(max(id),0) FROM risk_event") or 0)
        rows = []
        for i, h in enumerate(hits, 1):
            rows.append({"id": base + i, "trade_date": trade_date, "account_id": account_id,
                         "rule_id": h["rule_id"], "symbol": h["symbol"], "metric": h["metric"],
                         "value": h["value"], "action": h["action"], "status": "open",
                         "acked_by": None, "acked_at": None, "reason": None,
                         "created_at": datetime.now()})
        return self._upsert("risk_event", pd.DataFrame(rows))

    def count_open_block_buy(self, account_id: str = "*") -> int:
        return int(self.scalar(
            "SELECT count(*) FROM risk_event WHERE action='BLOCK_BUY' AND status='open'"
            " AND (account_id = ? OR account_id = '*')", [account_id]) or 0)

    def list_risk_events(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        if status:
            return self.query_df("SELECT * FROM risk_event WHERE status = ?"
                                 " ORDER BY trade_date DESC, id DESC LIMIT ?", [status, limit])
        return self.query_df("SELECT * FROM risk_event ORDER BY trade_date DESC, id DESC"
                             " LIMIT ?", [limit])

    def ack_risk_event(self, event_id: int, actor: str, reason: str) -> None:
        self.execute("UPDATE risk_event SET status='acked', acked_by=?, acked_at=?, reason=?"
                     " WHERE id=? AND status='open'", [actor, datetime.now(), reason, event_id])

    # ---------------------------------------------------------------- P2：信号
    def create_signal(self, rec: dict) -> None:
        self._upsert("signal_run", pd.DataFrame([rec]))

    def write_signal_items(self, run_id: str, df: pd.DataFrame) -> int:
        df = df.copy()
        df["run_id"] = run_id
        return self._upsert("signal_item", df[["run_id", "symbol", "target_weight",
                                              "current_weight", "delta", "attribution"]])

    def get_signal(self, run_id: str) -> dict:
        df = self.query_df("SELECT * FROM signal_run WHERE run_id = ?", [run_id])
        if df.empty:
            raise KeyError(f"signal 不存在：{run_id}")
        rec = df.iloc[0].to_dict()
        if isinstance(rec.get("checks"), str) and rec["checks"]:
            rec["checks"] = json.loads(rec["checks"])
        return rec

    def signal_items(self, run_id: str) -> pd.DataFrame:
        return self.query_df("SELECT * FROM signal_item WHERE run_id = ?"
                             " ORDER BY target_weight DESC", [run_id])

    def list_signals(self, trade_date: date | None = None, limit: int = 50) -> pd.DataFrame:
        if trade_date:
            return self.query_df("SELECT * FROM signal_run WHERE trade_date = ?"
                                 " ORDER BY created_at DESC LIMIT ?", [trade_date, limit])
        return self.query_df("SELECT * FROM signal_run ORDER BY trade_date DESC, created_at DESC"
                             " LIMIT ?", [limit])

    def set_signal_status(self, run_id: str, status: str, actor: str,
                          reason: str | None = None) -> None:
        self.execute("UPDATE signal_run SET status=?, reason=?, published_at=?"
                     " WHERE run_id=?", [status, reason, datetime.now(), run_id])

    # ---------------------------------------------------------------- P2：模拟盘
    def create_paper_account(self, rec: dict) -> None:
        self._upsert("paper_account", pd.DataFrame([rec]))

    def get_paper_account(self, account_id: str) -> dict:
        df = self.query_df("SELECT * FROM paper_account WHERE account_id = ?", [account_id])
        if df.empty:
            raise KeyError(f"account 不存在：{account_id}")
        rec = df.iloc[0].to_dict()
        if isinstance(rec.get("cost_model"), str) and rec["cost_model"]:
            rec["cost_model"] = json.loads(rec["cost_model"])
        return rec

    def list_paper_accounts(self) -> pd.DataFrame:
        return self.query_df("SELECT * FROM paper_account ORDER BY created_at")

    def save_paper_orders(self, df: pd.DataFrame) -> int:
        # 表有 PK(order_id) 与 UNIQUE(idempotency_key) 双约束，必须显式指定冲突目标
        return self._upsert("paper_order", df, conflict=["idempotency_key"])

    def paper_orders(self, account_id: str) -> pd.DataFrame:
        return self.query_df("SELECT * FROM paper_order WHERE account_id = ?"
                             " ORDER BY exec_date, symbol", [account_id])

    def save_paper_equity(self, df: pd.DataFrame) -> int:
        return self._upsert("paper_equity", df)

    def paper_equity(self, account_id: str) -> pd.DataFrame:
        df = self.query_df("SELECT * FROM paper_equity WHERE account_id = ? ORDER BY ts",
                           [account_id])
        if not df.empty:
            df["ts"] = pd.to_datetime(df["ts"]).dt.date
        return df

    def save_paper_positions(self, df: pd.DataFrame) -> int:
        return self._upsert("paper_position", df)

    def paper_positions(self, account_id: str, ts: date | None = None) -> pd.DataFrame:
        if ts:
            return self.query_df("SELECT * FROM paper_position WHERE account_id=? AND ts=?"
                                 " ORDER BY weight DESC", [account_id, ts])
        return self.query_df("SELECT * FROM paper_position WHERE account_id=? ORDER BY ts",
                             [account_id])

    def append_paper_ledger(self, df: pd.DataFrame) -> int:
        base = int(self.scalar("SELECT coalesce(max(id),0) FROM paper_ledger") or 0)
        df = df.copy()
        df["id"] = range(base + 1, base + 1 + len(df))
        df["created_at"] = datetime.now()
        return self._upsert("paper_ledger", df)

    def paper_ledger(self, account_id: str) -> pd.DataFrame:
        return self.query_df("SELECT * FROM paper_ledger WHERE account_id=? ORDER BY id",
                             [account_id])

    def save_recon(self, df: pd.DataFrame) -> int:
        return self._upsert("recon_check", df)

    def recon(self, run_id: str) -> pd.DataFrame:
        return self.query_df("SELECT * FROM recon_check WHERE run_id=? ORDER BY ts", [run_id])

    def job_status(self, trade_date: date | None = None) -> pd.DataFrame:
        if trade_date:
            return self.query_df(
                "SELECT * FROM job_run WHERE trade_date = ? ORDER BY job_id, attempt",
                [trade_date])
        return self.query_df("SELECT * FROM job_run ORDER BY trade_date DESC, job_id LIMIT 200")


class CalendarError(RuntimeError):
    """QUANT-D-001 交易日历缺失。"""
