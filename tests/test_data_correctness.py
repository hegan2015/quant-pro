"""真实数据正确性双跑（L4）：库内数据 vs 独立实现，容差 1e-6。

无行情库时自动 skip（保证 CI 在无网络/无数据环境仍可通过，但交付验收必须带库跑）。
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from core.config import settings

import numpy as np
import pandas as pd
import pytest

from core.config import settings
from core.engine.panels import load
from core.factor.evaluate import forward_return, ic_series
from core.factor.registry import REGISTRY, compute
from core.factor.standardize import standardize
from core.market.adjust import annualize, simple_returns
from core.market.tradability import floor_lot
from core.services import candidate_symbols
from core.store.duckdb_store import DuckDBStore

DB = os.path.join(settings.ROOT, "data", "mkt.duckdb")


def _has_data() -> bool:
    if not os.path.exists(DB):
        return False
    try:
        st = DuckDBStore(DB)
        try:
            return st.bar_count() > 100000
        finally:
            st.close()
    except Exception:
        return False


needs_data = pytest.mark.skipif(not _has_data(),
                                reason="需要真实行情库（先跑 scripts/fetch_all.py）")


@pytest.fixture(scope="module")
def store():
    st = DuckDBStore(DB)
    yield st
    st.close()


@pytest.fixture(scope="module")
def panels(store):
    syms = candidate_symbols(store, date(2016, 1, 4), n=600)
    return load(store, date(2016, 1, 4), date(2018, 12, 31), symbols=syms)


@needs_data
def test_adj_close_equals_sql(store, panels):
    """连续价 = 原始价 × 复权因子：SQL 与面板双跑一致（TC-D-03 的真实数据版）。"""
    sql = store.query_df(
        "SELECT ts, symbol, close * adj_factor AS adj FROM daily_bar"
        " WHERE symbol IN (SELECT UNNEST(?)) AND ts BETWEEN ? AND ?",
        [panels.symbols[:50], date(2016, 1, 4), date(2016, 3, 1)])
    wide = sql.pivot(index="ts", columns="symbol", values="adj")
    got = panels.adj_close.loc[wide.index, wide.columns]
    assert float((wide - got).abs().max().max()) < 1e-4


@needs_data
def test_returns_match_independent_sql(store, panels):
    """日收益双跑（TC-B-02）：连续有行情的日子必须与 SQL lag 完全一致；
    停牌缺行的日子我们的口径是「沿用上一价 → 收益 0」，SQL 的跨缺口收益不得用作参考。"""
    sym = panels.symbols[0]
    sql = store.query_df(
        "SELECT ts, close * adj_factor AS c, "
        " (close * adj_factor) / lag(close * adj_factor) OVER (ORDER BY ts) - 1 AS r"
        " FROM daily_bar WHERE symbol = ? ORDER BY ts", [sym])
    sql["ts"] = pd.to_datetime(sql["ts"]).dt.date
    sql = sql.set_index("ts")
    mine = simple_returns(panels.adj_close[[sym]])[sym]
    have = set(sql.index)
    consecutive = [t for t in mine.index if t in have]
    prev_of = {t: max([x for x in sql.index if x < t], default=None) for t in consecutive}
    gap_days = [t for t in consecutive
                if prev_of[t] is not None and
                len([d for d in panels.days if prev_of[t] < d < t]) > 0]
    strict = [t for t in consecutive if t not in set(gap_days)]
    ref = sql.loc[[t for t in strict if t in sql.index], "r"]
    got = mine.reindex(ref.index)
    m = ref.notna() & got.notna()
    assert float((ref[m] - got[m]).abs().max()) < 1e-9, "非缺口日收益必须逐值一致"
    assert len(gap_days) >= 0
    # 缺口日（停牌）收益必须为 0
    if gap_days:
        assert float(mine.reindex(gap_days).abs().max()) == 0.0


@needs_data
def test_ic_matches_sql_rank_correlation(store, panels):
    """IC 双跑：pandas Spearman vs SQL 秩相关（TC-F-06 的真实数据版）。"""
    f = standardize(compute("mom_20", panels), 1, min_n=50)[0]
    fwd = forward_return(panels.adj_close, 20)
    ics = ic_series(f, fwd, min_n=50)
    assert len(ics) > 10
    ts = ics.index[len(ics) // 2]
    sym_list = list(f.columns)
    pair = pd.DataFrame({"f": f.loc[ts].dropna(), "r": fwd.loc[ts].dropna()}).dropna()
    pair.insert(0, "symbol", pair.index)
    # Spearman 的并列值取平均秩：avg_rank = min_rank + (组内个数 - 1) / 2
    # 注册与查询必须在同一 cursor（父连接注册对 cursor 不可见）
    sql_ic = float(store.query_df_with("_icpair", pair,
        """SELECT corr(rf, rr) AS c FROM (
             SELECT rank() OVER (ORDER BY f) + (count(*) OVER (PARTITION BY f) - 1) / 2.0 rf,
                    rank() OVER (ORDER BY r) + (count(*) OVER (PARTITION BY r) - 1) / 2.0 rr
             FROM _icpair)""")["c"].iloc[0])
    assert float(sql_ic) == pytest.approx(float(ics.loc[ts]), abs=1e-9), \
        "SQL 平均秩相关必须与向量化 IC 逐值一致（并列值处理是常见缺陷点）"


@needs_data
def test_annualization_matches_calendar(store, panels):
    """年化必须按交易日历天数，与自然日无关（TC-B-02）。"""
    n = len(panels.days)
    total = float(panels.adj_close.iloc[-1, 0] / panels.adj_close.iloc[0, 0] - 1)
    assert annualize(total, n) == pytest.approx((1 + total) ** (252 / n) - 1, abs=1e-12)


@needs_data
def test_buy_and_hold_equals_adjusted_return(store, panels):
    """TC-B-01/03 真实数据版：单标的买入不动，引擎净值必须等于其复权价收益
    （建仓日按次日开盘价），且持有期日收益与复权日收益逐值一致。"""
    from core.engine.execution import BacktestConfig, Engine
    from core.strategy.base import Ctx, Strategy, TargetPortfolio
    from core.strategy.constraints import Constraints

    sym = panels.symbols[0]

    class HoldOne(Strategy):
        strategy_id = "hold_one"
        version = "v1"

        def rebalance_days(self, ctx, start, end):
            return [ctx.days[1]]

        def generate(self, view, ts):
            return TargetPortfolio(weights={sym: 1.0})

    ctx = Ctx(panels, {}, {s: {"list_date": date(2010, 1, 1)} for s in panels.symbols},
              pd.Series(0.0, index=panels.days))
    zero = {"commission_bp": 0, "min_commission": 0, "stamp_tax_sell_bp": 0,
            "transfer_bp": 0, "slippage_bp": 0}
    cfg = BacktestConfig(strategy_id="hold_one", start=panels.days[0], end=panels.days[-1],
                         initial_capital=1_000_000.0, cost=zero,
                         params={"max_stale_days": 20})
    res = Engine(panels, ctx, HoldOne(), cfg,
                 Constraints(max_weight=1.0, max_positions=1)).run()
    nav = res["equity"]["nav"]
    entry = panels.days[2]
    # 建仓价 = 真实开盘价折算到当日复权单位，按 4 位小数舍入（引擎既定规则）
    ratio = float(panels.adj_close.loc[entry, sym]) / float(panels.close.loc[entry, sym])
    adj_open = float(Decimal(str(round(float(panels.open.loc[entry, sym]) * ratio, 4))))
    qty = floor_lot(1_000_000.0 / adj_open)
    ref = (1_000_000.0 - qty * adj_open + qty * float(
        panels.adj_close.loc[panels.days[-1], sym])) / 1_000_000.0
    assert abs(float(nav.iloc[-1]) - ref) < 1e-6, \
        f"买入持有净值 {nav.iloc[-1]:.6f} ≠ 复权口径手算 {ref:.6f}，净值或账本有缺陷"
    ra = panels.adj_close[sym].pct_change().dropna()   # 复权日收益率
    rn = nav.pct_change().dropna()
    # 整手后会有残余现金（不产生收益），参考式必须按「市值/总资产」权重折算，
    # 否则拿全仓收益去比含现金净值会得出假偏差
    eq = res["equity"]
    w = (eq["mv"] / (eq["mv"] + eq["cash"])).shift(1)
    common = [d for d in rn.index if d in ra.index and d > entry]
    assert common, "持有期样本为空"
    dev = [abs(float(rn[d] - float(w[d]) * float(ra[d]))) for d in common]
    assert max(dev) < 1e-6, f"净值日收益与复权收益（按现金权重折算）最大偏差 {max(dev):.2e}"


@needs_data
def test_same_config_hash_reproduces_identical_equity(store):
    """TC-B-15：同 config_hash 重跑，净值序列必须逐值相等（容差 0）。"""
    from core.services import backtest as run_bt
    params = {"top_n": 10, "factors": {"mom_20": 0.5, "vol_60": 0.5},
              "constraints": {"max_weight": 0.2, "max_positions": 10, "min_positions": 1}}
    a = run_bt(store, "s2_multifactor", params, date(2019, 1, 4), date(2019, 12, 31),
               universe_size=300, sensitivity=False, persist=False,
               train_end=date(2019, 7, 1))
    b = run_bt(store, "s2_multifactor", params, date(2019, 1, 4), date(2019, 12, 31),
               universe_size=300, sensitivity=False, persist=False,
               train_end=date(2019, 7, 1))
    assert a["config_hash"] == b["config_hash"], "同配置必须同哈希"
    assert (a["equity"]["nav"].to_numpy() == b["equity"]["nav"].to_numpy()).all(), \
        "同哈希重跑的净值必须逐值相等"
    # run_id 是实例标识，比较结果时排除；其余列必须逐值一致
    cols = [c for c in a["orders"].columns if c != "run_id"]
    assert a["orders"][cols].equals(b["orders"][cols]), "订单明细也必须一致"


@needs_data
def test_liquidation_basket_is_deterministic(store):
    """S1 依赖流动性篮子排序：并列值下若不加 symbol 二级排序键，同配置两次会选到不同篮子。

    回归背景：实测同配置两次跑出 -7.63% 与 -7.56% 两种结果，即源于此。
    """
    from core.services import backtest as run_bt
    kw = dict(universe_size=1000, initial_capital=10_000_000.0, sensitivity=False,
              persist=False, train_end=date(2020, 6, 30))
    a = run_bt(store, "s1_trend", {"top_n": 50, "step_days": 5},
               date(2019, 1, 4), date(2020, 12, 31), **kw)
    b = run_bt(store, "s1_trend", {"top_n": 50, "step_days": 5},
               date(2019, 1, 4), date(2020, 12, 31), **kw)
    assert a["config_hash"] == b["config_hash"]
    assert (a["equity"]["nav"].to_numpy() == b["equity"]["nav"].to_numpy()).all(), \
        "流动性篮子排序必须确定性，否则回测结果不可复现"


@needs_data
def test_reproducible_across_processes_with_different_hash_seed(store, tmp_path):
    """跨进程可复现：同配置在两个不同 PYTHONHASHSEED 的子进程里必须得到逐值相同的净值。

    回归背景：撮合曾遍历 `set`，其迭代顺序随字符串哈希随机化变化；
    同进程内两次跑完全一致（掩盖缺陷），只有换进程才暴露 -7.63% vs -7.57% 的差异。
    因此本用例必须用子进程 + 不同哈希种子来复现历史缺陷形态。

    子进程用「导出的独立小库」而非主库：主库可能被验收进程持有写锁，
    子进程直连会 IO Error（那是环境竞争，不是可复现性缺陷）。
    """
    import subprocess
    import sys

    slice_db = str(tmp_path / "repro_slice.duckdb")
    store.con.execute(f"ATTACH '{slice_db}' AS sl")
    for tbl, where in (
        ("daily_bar", "ts BETWEEN DATE '2019-01-04' AND DATE '2020-12-31'"),
        ("trade_calendar", "trade_date BETWEEN DATE '2019-01-01' AND DATE '2020-12-31'"),
        ("instrument", "TRUE"),
        ("index_bar", "ts BETWEEN DATE '2019-01-04' AND DATE '2020-12-31'"),
    ):
        store.con.execute(f"CREATE TABLE sl.{tbl} AS SELECT * FROM main.{tbl} WHERE {where}")
    store.con.execute("DETACH sl")

    snippet = (
        "import sys,hashlib;sys.path.insert(0,%r);"
        "from datetime import date;"
        "from core.store.duckdb_store import DuckDBStore;"
        "from core.services import backtest;"
        "r=backtest(DuckDBStore(%r),'s1_trend',{'top_n':20,'step_days':5},"
        "date(2019,1,4),date(2020,12,31),universe_size=300,"
        "initial_capital=10_000_000.0,sensitivity=False,persist=False,"
        "train_end=date(2020,6,30));"
        "nav=[round(float(x),10) for x in r['equity'].nav];"
        "print(hashlib.sha256(repr(nav).encode()).hexdigest())"
    ) % (str(settings.ROOT), slice_db)
    outs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        res = subprocess.run([sys.executable, "-c", snippet], cwd=str(settings.ROOT),
                             capture_output=True, text=True, env=env, timeout=900)
        assert res.returncode == 0, res.stderr[-800:]
        outs.append(res.stdout.strip().splitlines()[-1])
    assert outs[0] == outs[1], "同配置跨进程结果不一致：存在依赖哈希随机化/集合顺序的缺陷"


@needs_data
def test_universe_no_survivorship_bias(store):
    """历史某日的样本池必须包含此后退市标的（FR-D-01 / TC-D-01）。"""
    as_of = date(2018, 6, 29)
    uni = store.universe(as_of)
    later = store.query_df(
        "SELECT symbol FROM instrument WHERE list_date <= ? AND delist_date > ?",
        [date(2018, 6, 29), date(2018, 6, 29)])
    assert set(later["symbol"]) <= set(uni["symbol"]), "已退市标的不得从历史池剔除"


@needs_data
def test_no_lookahead_in_factor_on_real_data(store, panels):
    """真实数据上的 LAG-4：因子在 T 日的值 = 只用 ≤T 数据重算（TC-B-23）。"""
    from core.engine.lookahead_guard import _truncate, lag4_factor_truncation
    res = lag4_factor_truncation(panels, list(REGISTRY), sample=6)
    assert res.status == "pass", res.detail
