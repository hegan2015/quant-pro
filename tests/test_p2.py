"""P2 内核用例：风控 / 信号 / 模拟盘（TC-R / TC-G / TC-P 的可自动化部分）。

全部使用独立临时库与合成行情，不依赖主库与网络。
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core.risk import engine as risk
from core.signal import service as sig
from core.paper import service as paper
from core.store.duckdb_store import DuckDBStore

SYMS = [f"S{i:03d}.SZ" for i in range(40)]


def make_store(tmp_path, n_days: int = 320) -> DuckDBStore:
    st = DuckDBStore(str(tmp_path / "p2.duckdb"))
    days, d = [], date(2023, 1, 2)
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    st.upsert_calendar(days)
    rng = np.random.default_rng(7)
    rows = []
    for s in SYMS:
        px = 10.0 + rng.uniform(0, 40)
        closes = px * np.cumprod(1 + rng.normal(0.0004, 0.015, n_days))
        for i, day in enumerate(days):
            c = float(closes[i])
            rows.append({"ts": day, "symbol": s, "open": c * 0.995, "high": c * 1.02,
                         "low": c * 0.98, "close": c, "pre_close": float(closes[i - 1]) if i else c,
                         "volume": 1_000_000, "amount": c * 1_000_000, "adj_factor": 1.0,
                         "float_share": 1e8, "limit_up": round(c * 1.1, 2),
                         "limit_down": round(c * 0.9, 2), "is_suspended": False,
                         "is_final": True, "source": "test",
                         "fetched_at": pd.Timestamp("2024-01-01"), "data_version": "t1"})
    st.upsert_bars(pd.DataFrame(rows))
    st.upsert_instruments(pd.DataFrame([
        {"symbol": s, "name": s, "exchange": "SZSE", "board": "main",
         "industry_l1": f"行业{i % 5}", "list_date": date(2015, 1, 1), "delist_date": None,
         "is_st": False, "total_share": None, "float_share": None}
        for i, s in enumerate(SYMS)]))
    idx = pd.DataFrame([{"ts": day, "index_code": "000300",
                         "close": 3500 * (1 + 0.0003 * i), "amount": 1e11,
                         "data_version": "t1"} for i, day in enumerate(days)])
    st.upsert_index_bars(idx)
    risk.ensure_rules(st)
    return st


# ------------------------------------------------------------------ 风控（TC-R）
def test_rule_hit_semantics(tmp_path):
    st = make_store(tmp_path, 40)
    r = risk.Rule("x", "x", "position.weight", ">", 0.10, "REJECT_ORDER")
    assert r.hit(0.11) and not r.hit(0.10)
    r2 = risk.Rule("y", "y", "symbol.is_st", "in", 1, "REJECT_ORDER", enabled=False)
    assert not r2.hit(1.0), "停用规则不得命中"


def test_block_buy_only_blocks_buys_and_needs_ack(tmp_path):
    st = make_store(tmp_path, 40)
    snap = risk.Snapshot(trade_date=date(2023, 3, 1), portfolio_max_drawdown=0.25)
    hits = risk.evaluate(st, snap)
    assert any(h["action"] == "BLOCK_BUY" for h in hits)
    assert risk.buy_blocked(hits)
    assert risk.order_blocked(hits, "S000.SZ") is None, "熔断不应拒卖出/已有持仓"
    assert risk.circuit_breaker_open(st)
    ev = st.list_risk_events(status="open")
    assert len(ev) >= 1
    st.ack_risk_event(int(ev.id.iloc[0]), "tester", "复核通过")
    assert not risk.circuit_breaker_open(st), "人工 ack 后熔断才解除"


def test_weight_and_turnover_reject(tmp_path):
    st = make_store(tmp_path, 40)
    snap = risk.Snapshot(trade_date=date(2023, 3, 1),
                         positions={"S000.SZ": {"weight": 0.15}},
                         portfolio_turnover_daily=0.7)
    hits = risk.evaluate(st, snap)
    assert risk.order_blocked(hits, "S000.SZ") == "R-WEIGHT-01"
    assert any(h["rule_id"] == "R-TURNOVER-01" for h in hits)


# ------------------------------------------------------------------ 信号（TC-G）
def test_signal_draft_then_publish_and_withdraw(tmp_path):
    st = make_store(tmp_path)
    day = st.trade_days(date(2024, 1, 1), date(2024, 6, 30))[-1]
    out = sig.build_signal(st, "s2_multifactor",
                           {"top_n": 10, "factors": {"mom_20": 0.5, "vol_60": 0.5},
                            "constraints": {"max_weight": 0.2, "max_positions": 10,
                                            "min_positions": 1}}, day)
    assert out["status"] == "draft" and out["n_items"] == 10
    with pytest.raises(sig.PublishBlocked):
        sig.publish(st, out["run_id"], "pm", confirm=False)
    pub = sig.publish(st, out["run_id"], "pm", confirm=True)
    assert pub["status"] == "published"
    with pytest.raises(sig.PublishBlocked):
        sig.publish(st, out["run_id"], "pm", confirm=True), "已发布不可重复发布"
    with pytest.raises(sig.PublishBlocked):
        sig.withdraw(st, out["run_id"], "pm", "")
    w = sig.withdraw(st, out["run_id"], "pm", "数据修正后 stale")
    assert w["status"] == "withdrawn"


def test_publish_blocked_by_blocking_issue(tmp_path):
    st = make_store(tmp_path)
    day = st.trade_days(date(2024, 1, 1), date(2024, 6, 30))[-1]
    out = sig.build_signal(st, "s2_multifactor",
                           {"top_n": 10, "factors": {"mom_20": 1.0},
                            "constraints": {"max_weight": 0.2, "max_positions": 10,
                                            "min_positions": 1}}, day)
    st.write_issues(pd.DataFrame([{"ts": day, "symbol": "*", "field": "coverage",
                                   "kind": "LOW_COVERAGE", "detail": "x", "blocking": True}]))
    with pytest.raises(sig.PublishBlocked) as ei:
        sig.publish(st, out["run_id"], "pm", confirm=True)
    assert any("阻断 issue" in r for r in ei.value.reasons)
    assert st.get_signal(out["run_id"])["status"] == "draft", "校验不过不得变 published"


# ------------------------------------------------------------------ 模拟盘（TC-P）
def _publish_one(st, day):
    return sig.build_signal(st, "s2_multifactor",
                            {"top_n": 10, "factors": {"mom_20": 0.5, "vol_60": 0.5},
                             "constraints": {"max_weight": 0.2, "max_positions": 10,
                                             "min_positions": 1}}, day)


def test_paper_settle_idempotent_and_reconciles(tmp_path):
    st = make_store(tmp_path)
    days = st.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    s1 = _publish_one(st, days[10])
    sig.publish(st, s1["run_id"], "pm", confirm=True)
    acct = paper.create_account(st, "t", 1_000_000.0, "s2_multifactor", days[0])
    a = paper.settle(st, acct, days[40])
    b = paper.settle(st, acct, days[40])          # 重跑
    orders = st.paper_orders(acct)
    assert len(orders) == len(orders.drop_duplicates("idempotency_key")), "重跑不得重复订单"
    led = st.paper_ledger(acct)
    assert len(led) == len(led.drop_duplicates("ref")), "流水只追加且按 ref 去重"
    assert a["nav"] == pytest.approx(b["nav"], abs=1e-9)
    assert a["recon_max_bp"] <= 1.0, f"对账差额 {a['recon_max_bp']}bp 超阈值"
    assert a["recon_open"] == 0


def test_paper_replay_does_not_touch_original(tmp_path):
    st = make_store(tmp_path)
    days = st.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    s1 = _publish_one(st, days[10])
    sig.publish(st, s1["run_id"], "pm", confirm=True)
    acct = paper.create_account(st, "t", 1_000_000.0, "s2_multifactor", days[0])
    paper.settle(st, acct, days[40])
    before_eq = st.paper_equity(acct).to_dict("list")
    before_led = st.paper_ledger(acct).to_dict("list")
    new_id = paper.replay(st, acct, days[20])
    assert new_id != acct
    assert st.paper_equity(acct).to_dict("list") == before_eq, "重放不得改原账户净值"
    assert st.paper_ledger(acct).to_dict("list") == before_led, "重放不得改原账户流水"


def test_paper_cash_identity_from_ledger(tmp_path):
    st = make_store(tmp_path)
    days = st.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    s1 = _publish_one(st, days[10])
    sig.publish(st, s1["run_id"], "pm", confirm=True)
    acct = paper.create_account(st, "t", 1_000_000.0, "s2_multifactor", days[0])
    paper.settle(st, acct, days[40])
    eq = st.paper_equity(acct)
    led = st.paper_ledger(acct)
    led = led.copy()
    led["ts"] = pd.to_datetime(led["ts"])
    for r in eq.itertuples():
        cash = 1_000_000.0 + float(led[led.ts <= pd.Timestamp(r.ts)]["amount"].sum())
        assert cash == pytest.approx(r.cash, abs=0.02), "现金必须等于流水之和"
