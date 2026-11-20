"""存储层用例（TC-D-01/02/06/07/09、TC-O-01、TC-B-12/15 的数据侧前提）。"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core.store.duckdb_store import CalendarError, DuckDBStore

SYM = ["AAA.SZ", "BBB.SZ", "CCC.SH"]


@pytest.fixture
def store(tmp_path):
    st = DuckDBStore(str(tmp_path / "t.duckdb"))
    st.upsert_instruments(pd.DataFrame([
        {"symbol": "AAA.SZ", "name": "A", "exchange": "SZSE", "board": "main",
         "list_date": date(2018, 1, 2), "delist_date": date(2024, 6, 30), "is_st": False,
         "industry_l1": "电子", "total_share": None, "float_share": None},
        {"symbol": "BBB.SZ", "name": "B", "exchange": "SZSE", "board": "gem",
         "list_date": date(2022, 3, 1), "delist_date": None, "is_st": True,
         "industry_l1": "医药", "total_share": None, "float_share": None},
        {"symbol": "CCC.SH", "name": "C", "exchange": "SSE", "board": "star",
         "list_date": date(2016, 1, 2), "delist_date": None, "is_st": False,
         "industry_l1": "半导体", "total_share": None, "float_share": None},
    ]))
    st.upsert_calendar([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)])
    return st


def bars_df(px=10.0, factor=1.5, fetched="2024-01-04 18:00:00", version="v1"):
    return pd.DataFrame([{
        "ts": date(2024, 1, d), "symbol": s, "open": px, "high": px * 1.02,
        "low": px * 0.98, "close": px, "pre_close": px, "volume": 1_000_000,
        "amount": px * 1_000_000, "adj_factor": factor, "float_share": 1e8,
        "limit_up": round(px * 1.1, 2), "limit_down": round(px * 0.9, 2),
        "is_suspended": False, "is_final": True, "source": "test",
        "fetched_at": pd.Timestamp(fetched), "data_version": version,
    } for d in (2, 3, 4) for s in SYM])


def test_upsert_is_idempotent(store):
    df = bars_df()
    store.upsert_bars(df)
    store.upsert_bars(df)
    assert store.bar_count() == 9, "重复写入不得产生重复行（FR-O-02）"


def test_upsert_updates_value_in_place(store):
    store.upsert_bars(bars_df(px=10.0))
    store.upsert_bars(bars_df(px=11.0))
    assert store.bar_count() == 9
    got = store.scalar("SELECT close FROM daily_bar WHERE symbol='AAA.SZ' AND ts=DATE '2024-01-02'")
    assert float(got) == 11.0


def test_data_version_stable_then_changes(store):
    store.upsert_bars(bars_df())
    v1 = store.data_version(date(2024, 1, 2), date(2024, 1, 4))
    for _ in range(5):
        store.upsert_bars(bars_df())
        assert store.data_version(date(2024, 1, 2), date(2024, 1, 4)) == v1, \
            "同数据重复计算必须同指纹（浮点 sum 的并行归约顺序不定，故用整数聚合）"
    store.upsert_bars(bars_df(px=12.0))
    assert store.data_version(date(2024, 1, 2), date(2024, 1, 4)) != v1


def test_universe_as_of_respects_list_and_delist(store):
    assert set(store.universe(date(2024, 1, 2))["symbol"]) == set(SYM)
    assert "AAA.SZ" not in set(store.universe(date(2024, 7, 1))["symbol"]), "退市后应剔除"
    assert "BBB.SZ" not in set(store.universe(date(2021, 1, 1))["symbol"]), "未上市应排除"


def test_calendar_error_on_missing_range(store):
    with pytest.raises(CalendarError):
        store.trade_days(date(2030, 1, 1), date(2030, 2, 1))


def test_pivot_matches_manual_adj(store):
    store.upsert_bars(bars_df(px=10.0, factor=1.5))
    p = store.pivot(date(2024, 1, 2), date(2024, 1, 4), "adj_close")
    assert float(p.loc[date(2024, 1, 2), "AAA.SZ"]) == pytest.approx(15.0)
    assert list(p.columns) == sorted(SYM)


def test_factor_write_read_roundtrip(store):
    wide = pd.DataFrame([[1.0, 2.0, 3.0]], index=[date(2024, 1, 2)], columns=SYM)
    store.write_factor("probe", wide)
    back = store.read_factor("probe")
    assert float(back.loc[date(2024, 1, 2), "BBB.SZ"]) == 2.0


def test_issue_blocking_filter(store):
    store.write_issues(pd.DataFrame([
        {"ts": date(2024, 1, 2), "symbol": "AAA.SZ", "field": "close", "kind": "X",
         "detail": "d", "blocking": True},
        {"ts": date(2024, 1, 3), "symbol": "BBB.SZ", "field": "close", "kind": "Y",
         "detail": "d", "blocking": False},
    ]))
    assert store.issue_count() == 2
    assert len(store.list_issues(blocking_only=True)) == 1


def test_amendment_keeps_original_row(store):
    """修正只追加流水，原行情行不被覆盖（ADR-013 / TC-D-09）。"""
    store.upsert_bars(bars_df(px=10.0))
    store.amend({"id": 1, "ts": date(2024, 1, 2), "symbol": "AAA.SZ", "field": "close",
                 "old_value": "10.0", "new_value": "10.5", "reason": "源端错位",
                 "actor": "tester", "marked_stale": True})
    assert float(store.scalar(
        "SELECT close FROM daily_bar WHERE symbol='AAA.SZ' AND ts=DATE '2024-01-02'")) == 10.0
    assert store.scalar("SELECT count(*) FROM data_amendment") == 1


def test_job_run_idempotent_and_status(store):
    store.job_start("j1", date(2024, 1, 2), 1, "j1|2024-01-02")
    store.job_finish("j1", date(2024, 1, 2), 1, "SUCCESS", 9)
    store.job_start("j1", date(2024, 1, 2), 1, "j1|2024-01-02")   # 重跑同键
    rows = store.job_status(date(2024, 1, 2))
    assert len(rows) == 1 and rows.iloc[0]["status"] == "running"


def test_run_persistence_roundtrip(store):
    from core.engine.execution import BacktestConfig
    cfg = BacktestConfig(strategy_id="s", start=date(2024, 1, 2), end=date(2024, 1, 4))
    store.create_run({
        "run_id": cfg.run_id, "strategy_id": "s", "version": "v1",
        "start_date": "2024-01-02", "end_date": "2024-01-04", "universe": "T",
        "initial_capital": 1000000.0, "cost_model": "{}", "benchmark": "000300",
        "config_hash": "abc", "seed": 7, "data_version": "v1", "status": "succeeded",
        "error": None, "lookahead_status": "pass", "metrics": '{"x":1}',
        "checklist": '{"status":"pass"}', "created_at": pd.Timestamp.now(),
        "finished_at": pd.Timestamp.now()})
    rec = store.get_run(cfg.run_id)
    assert rec["metrics"] == {"x": 1} and rec["lookahead_status"] == "pass"
