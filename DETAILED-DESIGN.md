# 智能量化系统 详细设计说明书（DETAILED DESIGN）

| 项 | 值 |
|---|---|
| 项目代号 | quant-pro |
| 文档版本 | v0.1（上游：[REQUIREMENTS.md](REQUIREMENTS.md) / [ARCHITECTURE.md](ARCHITECTURE.md)） |
| 编制日期 | 2026-11-20 |
| 约定 | 类型标注为 Python 3.12；金额 `Decimal`，价格 tick 0.01 元；日期 `datetime.date`；时区 `Asia/Shanghai` |

---

## 1 接口与分层纪律

| 规则 | 说明 |
|---|---|
| 四个稳定协议 | `MarketStore`、`DataSource`、`Factor`、`Strategy`、`BrokerBase`（第 5 个为撮合入口）。上层只依赖协议，不依赖实现。 |
| 依赖注入 | `core` 不 import `app`；`engine` 不 import `store`（通过传入的 `Bars` 只读视图） |
| 纯函数优先 | 因子计算、指标计算、约束裁剪为纯函数，输入 DataFrame 输出 DataFrame，便于双跑校验 |
| 禁写入口 | 行情/成交/ledger 的写入只允许经 `store` 的批量 upsert / append 方法，禁止裸 SQL 出现在业务模块 |

---

## 2 数据库设计（TimescaleDB）

### 2.1 主数据与行情

```sql
CREATE TABLE instrument (
  symbol        TEXT PRIMARY KEY,          -- '600519.SH' / '000001.SZ'
  name          TEXT NOT NULL,
  exchange      TEXT NOT NULL CHECK (exchange IN ('SSE','SZSE','BSE')),
  board         TEXT NOT NULL,             -- main/gem/star/bse
  industry_l1   TEXT,
  industry_l2   TEXT,
  list_date     DATE,
  delist_date   DATE,
  is_st_history JSONB DEFAULT '[]'         -- [{from,to,st_type}]，按日回溯
);

CREATE TABLE trade_calendar (
  trade_date DATE PRIMARY KEY,
  is_open    BOOLEAN NOT NULL
);

CREATE TABLE daily_bar (                     -- hypertable(ts)
  ts           DATE        NOT NULL,
  symbol       TEXT        NOT NULL,
  open         NUMERIC(12,4),
  high         NUMERIC(12,4),
  low          NUMERIC(12,4),
  close        NUMERIC(12,4),
  pre_close    NUMERIC(12,4),
  volume       BIGINT,                       -- 股
  amount       NUMERIC(20,4),                -- 元
  adj_factor   NUMERIC(20,10),               -- 后复权累积因子（基准=上市日）
  limit_up     NUMERIC(12,4),
  limit_down   NUMERIC(12,4),
  is_suspended BOOLEAN     NOT NULL DEFAULT FALSE,
  is_final     BOOLEAN     NOT NULL DEFAULT FALSE,   -- 一字/停复牌终态标记
  source       TEXT        NOT NULL,
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  data_version TEXT        NOT NULL,
  PRIMARY KEY (ts, symbol)
);
SELECT create_hypertable('daily_bar','ts', chunk_time_interval => INTERVAL '6 months');
ALTER TABLE daily_bar SET (timescaledb.compress, timescaledb.compress_segmentby='symbol');
SELECT add_compression_policy('daily_bar', INTERVAL '180 days');

CREATE TABLE index_bar (ts DATE, index_code TEXT, close NUMERIC(12,4),
  volume BIGINT, amount NUMERIC(20,4), PRIMARY KEY(ts, index_code));

CREATE TABLE fundamental_pit (
  ts DATE, symbol TEXT, field TEXT, report_period DATE,
  ann_date DATE NOT NULL,                     -- 公告日：PIT 对齐依据
  value NUMERIC(24,8), source TEXT,
  PRIMARY KEY (ts, symbol, field, report_period, ann_date)
);

CREATE TABLE data_issue (
  id BIGSERIAL PRIMARY KEY, ts DATE, symbol TEXT, field TEXT,
  kind TEXT, detail JSONB, blocking BOOLEAN, status TEXT,   -- open/ignored/fixed
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE data_amendment (                 -- ADR-013：只追加，不改原行
  id BIGSERIAL PRIMARY KEY, ts DATE, symbol TEXT, field TEXT,
  old_value TEXT, new_value TEXT, reason TEXT NOT NULL,
  actor TEXT NOT NULL, marked_stale BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

查询侧约定：`daily_bar` 原始价为准，连续价由视图函数生成，不冗余存多套价格。

```sql
CREATE VIEW v_adj_close AS
SELECT ts, symbol, close * adj_factor AS adj_close,
       open * adj_factor AS adj_open, high * adj_factor AS adj_high,
       low * adj_factor AS adj_low
FROM daily_bar;
```

### 2.2 研究、回测、信号、模拟盘、风控、运维

```sql
CREATE TABLE factor (factor_id TEXT PRIMARY KEY, name TEXT, direction SMALLINT,
  freq TEXT, deps JSONB, code_digest TEXT, enabled BOOL, deprecated_at DATE);
CREATE TABLE factor_value(ts DATE, symbol TEXT, factor_id TEXT, value NUMERIC(24,10),
  PRIMARY KEY(ts, symbol, factor_id));                     -- hypertable
CREATE TABLE factor_eval_snapshot(factor_id TEXT, window TEXT, ic_mean NUMERIC,
  ic_std NUMERIC, icir NUMERIC, t_stat NUMERIC, pos_ratio NUMERIC,
  quantile_returns JSONB, max_corr NUMERIC, calc_at TIMESTAMPTZ, PRIMARY KEY(factor_id, window));

CREATE TABLE strategy(strategy_id TEXT PRIMARY KEY, name TEXT, entrypoint TEXT, latest_version TEXT);
CREATE TABLE strategy_version(strategy_id TEXT, version TEXT, params JSONB,
  code_digest TEXT, created_at TIMESTAMPTZ, PRIMARY KEY(strategy_id, version));

CREATE TABLE backtest_run(
  run_id TEXT PRIMARY KEY, strategy_id TEXT, version TEXT,
  start_date DATE, end_date DATE, universe TEXT, initial_capital NUMERIC(20,2),
  cost_model JSONB, benchmark TEXT, config_hash TEXT NOT NULL, seed INT,
  data_version TEXT, status TEXT, error TEXT,
  metrics JSONB, checklist JSONB, lookahead_status TEXT,   -- pass/FAIL/skipped
  created_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
CREATE INDEX ON backtest_run(config_hash);
CREATE TABLE backtest_order(order_id BIGSERIAL PRIMARY KEY, run_id TEXT, ts DATE,
  symbol TEXT, side TEXT, qty INT, price NUMERIC, gross NUMERIC, fee NUMERIC,
  status TEXT, reject_reason TEXT);                        -- FR-B-05 留痕
CREATE TABLE backtest_equity(run_id TEXT, ts DATE, nav NUMERIC(20,6), gross_nav NUMERIC,
  exposure NUMERIC, turnover NUMERIC, cash NUMERIC, PRIMARY KEY(run_id, ts));
CREATE TABLE backtest_position(run_id TEXT, ts DATE, symbol TEXT, qty INT,
  cost NUMERIC, mv NUMERIC, pnl NUMERIC, PRIMARY KEY(run_id, ts, symbol));

CREATE TABLE signal_run(run_id TEXT PRIMARY KEY, trade_date DATE, strategy_id TEXT,
  version TEXT, status TEXT, reason TEXT, checks JSONB, created_by TEXT,
  created_at TIMESTAMPTZ, published_at TIMESTAMPTZ);
CREATE TABLE signal_item(run_id TEXT, symbol TEXT, target_weight NUMERIC,
  current_weight NUMERIC, delta NUMERIC, attribution JSONB, PRIMARY KEY(run_id, symbol));

CREATE TABLE paper_account(account_id TEXT PRIMARY KEY, name TEXT, initial_capital
  NUMERIC(20,2), cash NUMERIC(20,2), cost_model JSONB, strategy_id TEXT, status TEXT);
CREATE TABLE paper_order(order_id BIGSERIAL PRIMARY KEY, account_id TEXT, trade_date DATE,
  signal_run_id TEXT, symbol TEXT, side TEXT, req_qty INT, filled_qty INT,
  price NUMERIC, fee NUMERIC, status TEXT, reject_reason TEXT, idempotency_key TEXT UNIQUE);
CREATE TABLE paper_ledger(               -- 只追加；余额由流水推导（AP-08）
  id BIGSERIAL PRIMARY KEY, account_id TEXT, ts DATE, kind TEXT,   -- trade/fee/dividend/adjust/reverse
  symbol TEXT, qty INT, amount NUMERIC(20,6), ref TEXT, created_at TIMESTAMPTZ);
CREATE TABLE paper_position(account_id TEXT, ts DATE, symbol TEXT, qty INT,
  sellable_qty INT, cost NUMERIC, adj_cost NUMERIC, mv NUMERIC, unrealized NUMERIC,
  PRIMARY KEY(account_id, ts, symbol));
CREATE TABLE paper_equity(account_id TEXT, ts DATE, nav NUMERIC(20,6), cash NUMERIC,
  exposure NUMERIC, PRIMARY KEY(account_id, ts));
CREATE TABLE recon_diff(account_id TEXT, ts DATE, expected NUMERIC, actual NUMERIC,
  diff_bp NUMERIC, traced JSONB, status TEXT, PRIMARY KEY(account_id, ts));

CREATE TABLE risk_rule(rule_id TEXT PRIMARY KEY, name TEXT, scope TEXT, metric TEXT,
  op TEXT, threshold NUMERIC, action TEXT, priority INT, enabled BOOL, version INT);
CREATE TABLE risk_event(id BIGSERIAL PRIMARY KEY, trade_date DATE, account_id TEXT,
  rule_id TEXT, symbol TEXT, metric_value NUMERIC, action TEXT, status TEXT,  -- open/acked/cleared
  detail JSONB, acked_by TEXT, acked_at TIMESTAMPTZ);

CREATE TABLE job_run(job_id TEXT, trade_date DATE, attempt INT, status TEXT,
  rows_affected INT, error TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  idempotency_key TEXT UNIQUE, PRIMARY KEY(job_id, trade_date, attempt));
CREATE TABLE app_config(key TEXT PRIMARY KEY, value JSONB, updated_at TIMESTAMPTZ, updated_by TEXT);
```

DuckDB 等价实现：同表名同列，类型退化为 `DATE/DOUBLE/BIGINT/VARCHAR`，无 hypertable（按年分 Parquet 目录 + 视图union）；`NUMERIC(12,4)` 精度差异用 `DECIMAL` 显式声明保留，撮合层金额一律 Python `Decimal` 落库，避免浮点漂移。

---

## 3 数据字典要点

| 字段 | 口径 |
|---|---|
| `adj_factor` | 后复权累积因子，基准日=该股上市首日（因子=1）；连续价 = 原始价 × 当日因子 |
| `limit_up/limit_down` | 按 `pre_close` 与板块规则计算（主板 ±10%、创业板/科创板 ±20%、ST ±5%、北交所 ±30%），四舍五入到 0.01；新股上市首 N 日无限制→置 NULL 表示不约束 |
| `is_final` | 该日行情是否已收盘终态；盘中抓取产生的行默认 FALSE，EOD 覆盖为 TRUE；回测只接受 `is_final=TRUE` |
| `data_version` | `sha256(rows_digest + source + fetched_at_bucket)` 前 12 位，用于回测可复现绑定 |
| `fundamental_pit.value` | 原始报表值（元），比率类字段单独存小数；同 `(symbol, field, report_period)` 保留多版本公告（修订披露不覆盖） |

---

## 4 交易日历与复权算法

```python
def trading_days(start: date, end: date, direction: Literal["next","prev"], n: int) -> list[date]:
    """日历缺失（表内区间无任何记录）→ CalendarError；不得静默返回空。"""

def is_tradable(bar: Bar, side: Side) -> Reject | None:
    if bar.is_suspended or bar.close is None: return Reject("SUSPENDED")
    if not bar.is_final:                      return Reject("NOT_FINAL")
    if side == BUY  and bar.open >= bar.limit_up   and bar.high == bar.low: return Reject("LIMIT_UP_ONE_PU")
    if side == SELL and bar.open <= bar.limit_down and bar.high == bar.low: return Reject("LIMIT_DOWN_ONE_PU")
    return None
```

复权与除权识别（**实测修订，2026-11-20**）：
1. 东财后复权是**差额法**：同一标的 `hfq ≈ a + b·raw`（实测 600519 在 2016-01 区间
   `b≈5.025, a≈109.4`），因此「后复权因子单调不减」的常见假设**不成立**——
   价格上涨时因子会下降，这是正常现象，不得作为质量异常（`ADJ_FACTOR_SUSPECT` 已改为
   只标记单日跳变 ±50% 与因子非正）。
2. 因子来源：同一区间分别取 `fqt=0`（原始价）与 `fqt=2`（后复权价），
   `adj_factor = (hfq_close / raw_close) / 首日比值`；该比值与抓取窗口无关（已实测一致）。
3. **账本统一记在复权单位上**（ADR-014）：建仓金额 = `qty × 复权开盘价`，
   持仓市值 = `qty × 复权收盘`，因此净值增长 = 后复权总收益；
   分红与送转由复权价吸收，**不再单独计提现金分红**——旧实现按
   `市值 ×(r_adj − r_price)` 计提，对差额法不成立，实测造成净值偏离 ~2pp。
4. 真实价只用于三处：整手数量、可交易性（一字板/停牌/涨跌停）、以及「现金不足」的
   可负担股数估算；复权开盘价 = `raw_open × (adj_close / close)`，按 4 位小数舍入
   （2 位会引入约 0.05% 的单笔漂移）。
5. 停牌日沿用上一复权价估值，收益记 0；退市或最后真实行情滞后超过
   `max_stale_days`（默认 20 交易日）的持仓**强制清算**并留痕
   （`status=LIQUIDATED`，原因 `DELISTED` / `STALE_VALUATION`），不得用陈旧价长期估值。

---

## 5 核心协议（签名级）

```python
class DataSource(Protocol):
    def instruments(self, as_of: date) -> pd.DataFrame: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def adj_factors(self, symbol: str) -> pd.DataFrame: ...
    def fundamentals_pit(self, symbol: str) -> pd.DataFrame: ...   # 含 ann_date；无则返回空并标记
    def calendar(self, start: date, end: date) -> list[date]: ...

class MarketStore(Protocol):
    def upsert_bars(self, df: pd.DataFrame, source: str) -> WriteResult: ...
    def load_bars(self, start: date, end: date, symbols: Sequence[str] | None,
                  fields: Sequence[str]) -> pd.DataFrame: ...
    def pivot(self, start: date, end: date, field: str) -> pd.DataFrame: ...   # index=ts, columns=symbol
    def write_factor(self, factor_id: str, df: pd.DataFrame) -> WriteResult: ...
    def append_ledger(self, rows: list[LedgerRow]) -> None: ...                 # 只追加
    def data_version(self, start: date, end: date) -> str: ...

class Factor(ABC):
    id: str; direction: int; deps: tuple[str, ...]; freq: str = "day"
    def compute(self, ctx: "FactorContext") -> pd.DataFrame: ...               # index=ts, columns=symbol
    def validate(self, out: pd.DataFrame) -> list[Issue]: ...                  # NaN率/极值/相关性

class Strategy(ABC):
    def params_schema(self) -> type[BaseModel]: ...
    def rebalance_days(self, ctx: "AsOfView") -> list[date]: ...
    def generate(self, ctx: "AsOfView", date: date) -> TargetPortfolio: ...

class BrokerBase(ABC):   # BacktestBroker / PaperBroker / LiveBroker(v0.3)
    def quote(self, date: date, symbol: str, side: Side) -> Quote: ...
    def tradable(self, date: date, symbol: str, side: Side) -> Reject | None: ...
    def submit(self, order: Order) -> Fill: ...
```

### 5.1 AsOfView：结构性防未来函数

```python
class AsOfView:
    """只暴露 <= date 的数据；右端点越界立即抛 LookaheadAccessError。"""
    def bars(self, field: str, lookback: int) -> pd.DataFrame: ...   # 截断 [date-lookback, date]
    def factor(self, factor_id: str) -> pd.Series: ...              # 仅 date 当日截面
    def fundamental(self, field: str) -> pd.Series: ...             # WHERE ann_date <= date
    def next_day_return(self) -> NoReturn: ...                      # 显式禁用，报错提示改走引擎侧收益
```

引擎在调用 `strategy.generate` 前把窗口物化为独立副本（拷贝而非视图），使「偷看未来」在物理上不可得；`lookahead_guard` 另做逻辑校验（§10.4）。

---

## 6 撮合内核（回测与模拟盘共用）

### 6.1 逐日流程

```
for T in trading_days[start, end]:                      # 信号日 = T，成交日 = T+1
  1. target = strategy.generate(asof(T), T)             # 只含 ≤T 信息
  2. target = portfolio.apply_constraints(target, rules) # 单票/行业/持仓数/现金 → 迭代裁剪
  3. orders = diff(current_weights, target)              # 先卖后买（现金优先）
  4. orders = turnover_limit.trim(orders, max_turnover)  # 超限部分留痕 SKIPPED_TURNOVER
  5. for o in orders:
       exec_date = next_trading_day(T)
       if exec_date > end: break                        # 区间末不产生悬空订单
       reject = broker.tradable(exec_date, o.symbol, o.side)
       if reject: record_order(status=REJECTED, reason=reject); continue
       price = broker.quote(exec_date, o.symbol, o.side).open   # 或 VWAP，口径入 metrics
       qty   = floor_to_lot(cash_available / (price*(1+rate)), 100)   # 买入向下取整
       if o.side == SELL: qty = min(qty, position.sellable_qty)        # T+1 可售
       if qty == 0: record_order(status=REJECTED, reason='CASH_SHORT'); continue
       fee   = cost_model.calc(o.side, price, qty)
       book.apply_trade(...)                            # 现金/持仓/ledger/成本
  6. book.mark_to_market(exec_date)                     # 后复权估值
  7. risk_guard.check_post_trade(book, exec_date)       # 回撤/集中度 → 可能触发熔断（次日生效）
  8. equity.append(nav); positions.append(...)
```

### 6.2 舍入与数值规则

| 项 | 规则 |
|---|---|
| 真实价 | `Decimal(str(raw)).quantize(0.01, ROUND_HALF_UP)`（A 股最小报价 0.01 元） |
| 复权价 | `quantize(0.0001, ROUND_HALF_UP)`（记账单位，2 位会引入单笔 ~0.05% 漂移） |
| 买入数量 | `floor_lot(目标金额 / 复权开盘价)`；可负担上限按真实价与费率折算 |
| 卖出数量 | 允许零股一次卖光（`qty = position.qty`） |
| 金额 | 成交金额 `price*qty` 保留 2 位；费用保留 2 位（单笔最低 5 元） |
| 净值 | `nav = (cash + Σmv) / initial_capital`，6 位小数 |
| 累计误差 | 每次记账后断言 `cash == Σledger`，不等即 `ReconDiff`（不在末尾抹平） |
| 分红 | 不单独入账（复权价已含），避免与价格收益重复计入 |

### 6.3 成本模型

```python
@dataclass
class CostModel:
    commission_bp: Decimal = Decimal("2.5")   # 双边
    min_commission: Decimal = Decimal("5")
    stamp_tax_sell_bp: Decimal = Decimal("5") # 卖出单边（2023-08 起 0.05%）
    transfer_bp: Decimal = Decimal("0.1")     # 双边
    slippage_bp: Decimal = Decimal("5")       # 敏感性报告跑 0/5/10
    def buy(self, px, qty):  amt = px*qty; return max(amt*comm, min_comm) + amt*transfer
    def sell(self, px, qty): amt = px*qty; return max(amt*comm, min_comm) + amt*(transfer+stamp)
    def exec_price(self, px, side): return px*(1 + slippage) if side==BUY else px*(1 - slippage)
```
滑点作用于成交价而非事后扣减，使市值与现金口径自洽（否则 §6.2 的 ledger 断言会假阳性）。

### 6.4 拒单码

| 码 | 含义 | 是否终态 |
|---|---|---|
| `SUSPENDED` | 停牌 | 是 |
| `NOT_FINAL` | 行情未终态（模拟盘当日盘前） | 否，可重算 |
| `LIMIT_UP_ONE_PU` / `LIMIT_DOWN_ONE_PU` | 一字板无法成交 | 是 |
| `CASH_SHORT` | 现金不足（含整手后为 0） | 是 |
| `SELLABLE_SHORT` | T+1 不可卖 | 是 |
| `RISK_REJECT` | 风控预检拒绝（权重/换手/黑名单/熔断） | 是 |
| `DELISTED` | 退市进入清算路径 | 是 |
| `SKIPPED_TURNOVER` | 换手上限裁剪 | 是 |

---

## 7 因子实现

| 因子 | 公式（信号日 T 收盘可得） | 方向 |
|---|---|---|
| `mom_20/60/120` | `adj_close[T] / adj_close[T-n] - 1`，剔除首末非交易日 | +1 |
| `rev_5` | `-(adj_close[T]/adj_close[T-5]-1)` | 已按 +1 存 |
| `vol_60` | `std(r_daily, 60) * sqrt(252)`，`r` 用简单收益 | -1 |
| `turnover_20` | `mean(amount/流通市值, 20)` | -1（过热惩罚） |
| `size` | `ln(总市值)`，市值 = `close × 总股本`（PIT 股本） | -1（小市值溢价，标注环境依赖） |
| `ep` / `bp` / `sp` | `TTM归母净利/市值`、`净资产/市值`、`TTM经营现金流/市值` | +1 |
| `roe_ttm` | `TTM归母净利/平均净资产` | +1 |
| `gross_margin` | `(营收-营业成本)/营收` | +1 |
| `net_profit_yoy` | `当期TTM净利 / 去年同期TTM - 1` | +1 |
| `crowding` | `行业成交额占比 分位` | -1 |

截面处理链（唯一实现，禁止策略内自行标准化）：
```
raw → 停牌/缺失剔除 → winsorize(lower=0.01, upper=0.99 或 ±3σ)
    → z-score(mean/std, ddof=1) → * direction → factor_value
```
一致性：同一日截面内标的数 < 100 时不产出该日因子（写 `data_issue(LOW_COVERAGE)`），避免 z-score 退化。

---

## 8 组合构建与约束

```python
@dataclass
class Constraints:
    max_weight: Decimal = Decimal("0.10")
    max_industry_dev: Decimal = Decimal("0.08")
    min_positions: int = 20; max_positions: int = 50
    min_cash: Decimal = Decimal("0.0")
    max_turnover: Decimal = Decimal("0.6")     # 单次调仓单边/组合市值
    blacklist: set[str] = field(default_factory=set)

def apply_constraints(weights, constraints, industry, benchmark_weights):
    for _ in range(50):                         # 迭代裁剪（不引入 cvxpy）
        w = clip(weights, max_weight); w = renormalize(w, min_cash)
        w = cap_industry_dev(w, industry, benchmark_weights, max_industry_dev)
        w = select_top_n(w, constraints.max_positions)
        if converged(w): return w
    return w   # 未收敛 → 返回并记 warning（不静默）
```

打分合成：`score = Σ w_i * zscore_i`，其中 `w_i = ICIR_i(+窗口) / Σ|ICIR|`，窗口 `[T-24M, T-1]`（严格不含 T 之后）。
持仓选择：按 `score` 降序取 `max_positions`，等权起步再走约束裁剪。
基线策略：
- **S1 双均线择时**：`adj_close(000300)` 与 MA20/MA60 关系映射仓位 `{0, 0.5, 1.0}`，持仓用指数 ETF 近似（v0.1 用指数收盘价近似，报告标注）。
- **S2 多因子月度**：动量 25% + 低波 15% + 质量 20% + 估值 20% + 小市值 20%（权重按 §8 ICIR 覆盖初值）。
- **S3 行业轮动**：一级行业 3 月相对强度排序取 Top5，`crowding` 分位 > 0.8 的行业减半。

---

## 9 绩效与归因公式

| 指标 | 公式 |
|---|---|
| 累计收益 | `nav_end / nav_start - 1` |
| 年化收益 | `(1 + total) ** (252 / n_days) - 1` |
| 年化波动 | `std(r_p, ddof=1) * sqrt(252)` |
| Sharpe | `(ann_ret - rf) / ann_vol`，`rf` 默认 1.5% |
| Sortino | `(ann_ret - rf) / std(r_p[r_p<0]) * sqrt(252)` 下行波动口径 |
| 最大回撤 | `max(1 - nav_t / cummax(nav))`；记录峰谷日期与修复天数 |
| Calmar | `ann_ret / max_drawdown` |
| Beta / Alpha | `OLS(r_p - rf_daily ~ r_b - rf_daily)`，`alpha` 年化截距 |
| 跟踪误差 / IR | `std(r_p - r_b)*sqrt(252)`；`ann超额 / TE` |
| VaR95 | 历史法 `percentile(r_p, 5)`（非参数） |
| 胜率 | 有成交的平仓批次中 `pnl > 0` 占比；另报「日胜率」 |
| 盈亏比 | `mean(盈利批次 pnl) / |mean(亏损批次 pnl)|` |
| 年化换手 | `Σ单边成交额 / mean(组合市值) / 年数` |
| 成本占比 | `Σ(fee + slippage_amount) / 毛收益` |
| Brinson（简化） | `配置 = (wp-wb)*rb`；`选股 = wb*(rp-rb)`；`交互 = (wp-wb)*(rp-rb)`，按行业汇总 |
| 单票贡献 | `Σ_t w_{t-1} * r_t`（对数分解近似，报告注明） |

报告字段固定分五组：收益 / 风险 / 比值 / 交易 / 基准与结构。缺项渲染 `N/A` 并说明原因，不得留空。

---

## 10 回测服务

### 10.1 生命周期

`pending → running → succeeded | failed | LOOKAHEAD_FAIL | partial`；`succeeded` 之前必须完成：①门禁（10.4）②体检表（§14.3）③成本敏感性（FR-B-11）。

### 10.2 config_hash

```python
config_hash = sha256(canonical_json({
  "strategy": strategy_id, "version": version, "params": params,
  "start": start, "end": end, "universe": universe_digest,
  "cost": cost_model, "benchmark": benchmark, "seed": seed,
  "data_version": store.data_version(start, end), "code_digest": git_or_pkg_digest()
}))
```
同 hash 重跑要求：`backtest_equity` 全序列逐值相等（`TC-B-15`，容差 0）。

### 10.3 服务接口

```python
def run_backtest(req: BacktestRequest, principal) -> RunSummary
def compare_runs(run_ids: list[str]) -> ComparisonTable
def export_report(run_id, fmt: Literal["html","json","csv"]) -> Artifact
```

### 10.4 未来函数门禁（自动化）

| 检查 | 做法 | 失败判据 |
|---|---|---|
| LAG-1 前视替换 | 将 `T+1..T+5` 行情置 NaN 重跑，比较 `signal_item` 与 `nav` 序列 | 任何差异 → FAIL |
| LAG-2 财报时点 | 静态扫描 + 运行时断言：`fundamental` 查询必带 `ann_date <= T` | 违规 SQL → FAIL |
| LAG-3 复权 | 断言信号日窗口内不存在 `fetched_at > T` 的因子行参与计算 | FAIL |
| LAG-4 窗口右端 | 指标计算 `iloc[:n]` 不含 T+1；rolling 默认 `min_periods=n` | FAIL |
| LAG-5 停牌/退市 | 退市后仍出现的持仓 → 校验清算价使用 | FAIL |

---

## 11 信号服务

发布前置校验（任一不过即 `422` 并返回原因清单，不生成 `published`）：
数据 `is_final` 覆盖率 ≥ 99%；当日 `data_issue(blocking=true)` 为 0；来源回测 `lookahead_status = pass`；风控预检无 `RISK_REJECT`；区间末/非交易日禁止出信号。

写入顺序（单事务）：`signal_run(draft)` → `signal_item` 批量 → 校验汇总 `checks` → 状态迁移 `published`（`published_at/created_by` 必填）。撤回只允许 `published → withdrawn` 且必须带 `reason`。

---

## 12 模拟盘账本与对账

- 余额推导：`cash(T) = initial + Σ ledger.amount(T'≤T)`，`paper_account.cash` 为缓存列，日终与流水比对，不一致以流水为准并告警。
- 成交入口唯一：由已发布信号的次日订单生成，人工下单需 `role:pm` 且同样过风控（FR-R-05）。
- 幂等：`paper_order.idempotency_key = (account_id, trade_date, symbol, side, signal_run_id)`，重跑不重复成交。
- 对账公式：
```
expected_nav_gain = Σ position.qty_{T-1} * (adj_close_T/adj_close_{T-1} - 1) * mv_weight
                  + cash * rf_daily
                  - Σ fee_T
actual_nav_gain   = (cash_T + Σ mv_T) - (cash_{T-1} + Σ mv_{T-1})
diff_bp = (actual - expected) / nav_{T-1} * 10000      # |diff_bp| > 1 → recon_diff
```
超阈值时逐单追溯：按 `order_id` 重放记账，输出首个偏差来源（估值价、成本、除权、停牌沿用价）写入 `recon_diff.traced`。禁止加一条「调整」流水把差异抹平（红线，`TC-P-06`）。
- 重放（FR-P-06）：`replay(from_date)` 生成新 `account_id`（后缀 `-replay-<ts>`），原账本零写入。

---

## 13 风控规则引擎

规则表达式（`config/risk_rules.yaml`）：
```yaml
- rule_id: R-DRAWDOWN-01
  metric: portfolio.max_drawdown_since_arbitration   # 取水位期内峰值
  op: ">"
  threshold: 0.20
  action: BLOCK_BUY            # BLOCK_BUY / REDUCE / REJECT_ORDER / ALERT
  scope: {account: "*"}
  priority: 10
```
求值时机：`pre_trade`（下单前，逐单 + 组合预估）与 `post_trade`（日终，实际净值）。`BLOCK_BUY` 生效于次日撮合（v0.1 不强平）。判定结果：命中 → 订单 `RISK_REJECT` + `risk_event(open)`；解除须 `role:risk` 调 `POST /risk/events/{id}/ack` 或 `PUT /risk/rules/{id}`，操作人与原因必填。
内置规则见 FR-R-02，阈值可配但改动进 `app_config` 审计。

---

## 14 AI 研究台

### 14.1 流程
```
需求（自然语言）→ 口径澄清（缺失定义先问）→ 生成因子草稿代码
  → 静态检查 → 沙箱执行 → 数据校验 → 回测 + 体检表 → 人工确认 → 注册 factor/strategy_version
```

### 14.2 沙箱（隔离实测要求）
| 维度 | 限制 |
|---|---|
| import | 白名单 `pandas,numpy,scipy,datetime,datautils,math,statistics,core.factor.base,core.market.*`；其余 `ImportError` |
| 网络/文件 | 禁 socket/subprocess/os.path 写；工作目录只读挂载，输出只允许 `stdout` + 结果 DataFrame |
| 资源 | RLIMIT_AS 4GB、CPU 120s、墙钟 180s、输出行数 ≤ 200 万、递归深度 200 |
| 数据 | 只能拿 `AsOfView`，与策略同一物理隔离（§5.1） |
| 失败 | 原因回显给研究员，异常不吞；沙箱进程崩溃不影响 api/worker |

### 14.3 过拟合体检表（红线）
| 项 | 红线 |
|---|---|
| 样本外 vs 样本内 Sharpe | OOS < 0.3 或 OOS < 0.3×IS → FAIL |
| 参数扰动 ±20% | Sharpe 变号 或 跌幅 > 50% → WARN/FAIL |
| 5 分层单调性 | 不单调（Top-Bottom 收益符号异常）→ FAIL |
| 成本占毛收益 | > 40% → FAIL（高换手幻觉） |
| IC 衰减 | 20 期后 |IC| 不降反升异常 → WARN |
| 与已有因子相关性 | > 0.95 → 需确认（FR-F-05） |
FAIL 的策略不允许进入 P2 信号发布与模拟盘（引擎层强制，非仅前端提示）。

---

## 15 REST API（前缀 `/api`，全部需 Bearer）

| 方法 路径 | 用途 | 关键请求/响应 | 角色 |
|---|---|---|---|
| `GET /healthz` | 存活（免鉴权，仅 `/healthz`） | `{status, store_mode, latest_trade_date}` | — |
| `GET /instruments?as_of&type=index` | 标的池 | `[{symbol,name,industry,is_st}]` | viewer |
| `GET /bars?start&end&symbol&fields&adjust` | 行情 | `{rows:[{ts,open,...,adj_close}], data_version}` | viewer |
| `POST /jobs/{job_id}/run` | 触发作业 | `{trade_date?, force?}` → `{run_id}`；幂等 | data |
| `GET /jobs?trade_date&status` | 作业状态 | `[{job_id,status,rows_affected,error}]` | viewer |
| `GET /data/issues?blocking` | 质量问题 | `[...]` | viewer |
| `POST /data/amendments` | 数据修正留痕 | `{ts,symbol,field,new_value,reason}` → 201 | data |
| `GET /factors?window` | 因子清单 + 评估 | `[{factor_id,icir,quantiles,max_corr}]` | viewer |
| `POST /factors/{id}/evaluate` | 重算评估 | `{window}` | researcher |
| `GET /strategies` / `POST /strategies` | 策略 CRUD | `{strategy_id, version, params}` | researcher |
| `POST /backtests` | 起回测（202 + run_id） | `{strategy_id,version,params,start,end,universe,cost,seed}` | researcher |
| `GET /backtests/{run_id}` | 结果 | `{status,metrics,checklist,lookahead_status,config_hash}` | viewer |
| `GET /backtests/{run_id}/equity?freq` | 净值序列 | `[{ts,nav,drawdown}]` | viewer |
| `GET /backtests/{run_id}/orders?status=REJECTED` | 拒单明细 | `[{ts,symbol,side,reason}]` | viewer |
| `GET /backtests/{run_id}/report?fmt=html` | 报告下载 | `text/html` 或 JSON | viewer |
| `POST /backtests/compare` | 多列对比 | `{run_ids:[..]}` → `ComparisonTable` | researcher |
| `GET /signals?trade_date` / `POST /signals` | 信号查询/生成草稿 | `{strategy_id,version,trade_date}` | researcher |
| `POST /signals/{run_id}/publish` | 发布 | `{confirm:true}` → 200 / 422 原因清单 | pm |
| `POST /signals/{run_id}/withdraw` | 撤回 | `{reason}` | pm |
| `GET /paper/accounts` / `POST /paper/accounts` | 账户 | `{name, initial_capital, cost_model, strategy_id}` | pm |
| `GET /paper/accounts/{id}/positions?ts` | 持仓 | `[{symbol,qty,sellable_qty,cost,mv,unrealized}]` | viewer |
| `GET /paper/accounts/{id}/orders?status` | 订单 | 含 `reject_reason` | viewer |
| `GET /paper/accounts/{id}/reconciliation?range` | 对账 | `[{ts,diff_bp,status,traced}]` | pm |
| `POST /paper/accounts/{id}/replay` | 重放新副本 | `{from_date}` → 新 `account_id` | pm |
| `GET /risk/rules` / `PUT /risk/rules/{id}` | 规则 | `{threshold,enabled}` | risk |
| `GET /risk/events?status=open` / `POST /risk/events/{id}/ack` | 事件 | `{acked_by, reason}` | risk |
| `POST /ai-lab/sessions` / `POST /ai-lab/sessions/{id}/run` | 研究台 | 草稿 → 沙箱结果 + 体检表 | researcher |

错误响应统一：`{code:"QUANT-B-004", message:"...", trace_id:"...", detail:{...}}`；HTTP 映射 400 参数、401 未认证、403 越权、404 不存在、409 幂等冲突、422 业务校验不过、429 限流、503 存储不可用。

---

## 16 前端设计

> 界面层完整规格见 [UI-DESIGN.md](UI-DESIGN.md)（设计令牌、导航与角色可见性、逐页布局与状态矩阵、组件库、可视化与格式规范、a11y 与性能预算）；本节保留与后端契约相关的摘要。

技术：Vue 3 + Vite + Element Plus + Pinia + Chart.js（封装 `BaseChart`）。路由与角色绑定，未授权页显示 403 组件而非跳转空白。

```
/views/Dashboard.vue      净值+回撤双轴、今日信号卡、风控状态、数据新鲜度
/views/DataQuality.vue    异常表(可筛选)、修正留痕、作业列表、双源差异
/views/Research.vue       因子库(排序表) / IC 曲线 / 相关性矩阵 / 策略列表 / AI 会话
/views/Backtest.vue       表单(参数由 schema 动态渲染) → 进度(轮询 202) → 指标卡 → 曲线 → 成本敏感性 → 体检表 → 对比抽屉
/views/PaperTrading.vue   账户切换 / 持仓表 / 订单(拒单原因高亮) / 对账趋势 / 重放入口(确认框)
/components/              MetricCard, NavChart, DrawdownChart, HeatmapMonth, QuantileBar,
                          OrderTable, ReconDiffList, RiskEventDrawer, EmptyState, Forbidden
```

约定：长任务轮询 `GET /backtests/{id}`（指数退避 1→5s，上限 5min，可取消）；表格服务端分页；所有数字口径 tooltip 显示公式来源（`§9`）；免责声明常驻页脚。

---

## 17 调度作业

| job_id | cron（Asia/Shanghai） | 依赖 | 幂等键 | 超时/重试 |
|---|---|---|---|---|
| `fetch_calendar` | 1 1 1 * * | — | 年 | 60s / 3 |
| `fetch_instruments` | 17 6 * * 1 | calendar | 周 | 300s / 3 |
| `fetch_bars_daily` | 30 18 * * 1-5 | calendar | `trade_date` | 1800s / 3（断点续传标的集） |
| `fetch_adj_factors` | 45 18 * * 1-5 | bars | `trade_date` | 900s / 3 |
| `fetch_fundamentals` | 0 19 * * 1-5 | instruments | `trade_date` | 1800s / 3 |
| `quality_check` | 15 19 * * 1-5 | bars | `trade_date` | 600s / 1 |
| `factor_compute` | 30 19 * * 1-5 | quality, fundamentals | `trade_date` | 1200s / 2 |
| `signal_generate` | 45 19 * * 1-5 | factor | `trade_date` | 300s / 2 |
| `paper_settle` | 20 20 * * 1-5 | signal(前一日) | `trade_date` | 300s / 2 |
| `reconcile` | 35 20 * * 1-5 | paper_settle | `trade_date` | 120s / 2 |
| `report_refresh` | 45 20 * * 1-5 | reconcile | `trade_date` | 300s / 1 |

失败传播：上游 PARTIAL 时下游默认跳过并记录 `SKIPPED_UPSTREAM`；`force` 需 `role:data` 且在 `job_run` 标注。并发锁：同 `job_id + trade_date` 单实例（DB advisory lock），避免抓取重复。

---

## 18 配置项

| key（env / settings.yaml） | 默认 | 密钥 |
|---|---|---|
| `STORE_MODE` | `auto`（timescale→duckdb） | 否 |
| `PG_HOST/PORT/DB/USER` | `127.0.0.1/5433/quant/quant` | 否 |
| `PG_PASSWORD` | — | **是**（`~/.config/quant-pro/db_password`，600） |
| `TUSHARE_TOKEN` | 空→免费源并降级声明 | **是** |
| `CONSOLE_PORT` / `API_PORT` / `METRICS_PORT` | 8101 / 8102 / 8103 | 否 |
| `UNIVERSE` | `ALL_A` | 否 |
| `START_DATE` / `END_DATE` | 2016-01-01 / 2025-12-31 | 否 |
| `REBALANCE` | `monthly` | 否 |
| `COST_*` | §6.3 默认 | 否 |
| `RF_ANNUAL` | 0.015 | 否 |
| `FETCH_RATE_LIMIT` / `FETCH_CONCURRENCY` | 5 req/s / 8 | 否 |
| `RISK_*`（阈值） | FR-R-02 | 否 |
| `LLM_*`（base_url/api_key/model） | 空则禁用 AI 研究台 | **是** |
| `AUTH_TOKEN_SECRET` | — | **是** |

启动校验：缺密钥→明确报错并指出期望文件路径（不接受静默用默认口令）；文件权限 ≠ 600 时告警；任何配置文件不得提交真实口令（仓库只 `.example`）。

---

## 19 错误码与异常层次

| 码 | 异常 | 含义 |
|---|---|---|
| QUANT-D-001 | `CalendarError` | 交易日历缺失/区间无数据 |
| QUANT-D-002 | `DataIncomplete` | 覆盖率不足（`LOW_COVERAGE`） |
| QUANT-D-003 | `DataSourceUnavailable` | 外部源失败（含限流） |
| QUANT-B-001 | `TradabilityReject` | 停牌/一字板/未终态 |
| QUANT-B-002 | `CashShort` | 现金不足 |
| QUANT-B-003 | `SellableShort` | T+1 不可卖 |
| QUANT-B-010 | `LookaheadAccessError` | AsOfView 越界访问 |
| QUANT-B-011 | `LookaheadGateFail` | 门禁未通过（不可发布） |
| QUANT-B-012 | `ReproConflict` | 同 `config_hash` 结果不一致 |
| QUANT-S-001 | `PublishBlocked` | 发布前置校验不过（带原因清单） |
| QUANT-R-001 | `RiskReject` | 风控拒绝 |
| QUANT-R-002 | `CircuitBreakActive` | 熔断中，禁止新增买入 |
| QUANT-P-001 | `ReconDiff` | 对账超阈值 |
| QUANT-P-002 | `ImmutableLedger` | 试图改写流水/原账本 |
| QUANT-A-001 | `SandboxViolation` | 沙箱越权（import/网络/资源） |
| QUANT-A-002 | `ChecklistFail` | 体检表红线不过 |
| QUANT-O-001 | `StoreUnavailable` | 存储不可用（含容器挂） |
| QUANT-O-002 | `JobUpstreamSkipped` | 上游 PARTIAL 导致跳过 |
| QUANT-O-003 | `IdempotencyConflict` | 重复提交（409） |

---

## 20 CLI

```
quant bootstrap                 # 探测环境→选 python3.12→venv→依赖→schema→（可选）起容器
quant fetch --what bars --from 2016-01-01 --to 2026-11-20 [--resume]
quant factor --id all --range 2016-2025
quant evaluate --factor mom_20 --window 24m
quant backtest --strategy s2_multifactor --start 2016-01-01 --end 2025-12-31 \
               --universe ALL_A --cost default --out data/reports/
quant gate --run <id>           # 只跑未来函数门禁与体检表
quant signal --date 2026-11-20 [--publish]
quant paper init --capital 1000000 --strategy s2_multifactor
quant paper run --date 2026-11-20 ; quant paper reconcile --range 30d
quant job --list ; quant job run factor_compute --date 2026-11-20
quant serve                      # api + console（worker 独立进程 quant worker）
```
CLI 与 API 共用 `services` 层，禁止 CLI 走 HTTP 再回服务（减少一层脆弱性）。

---

## 21 可测性设计

| seam | 测试手段 |
|---|---|
| `MarketStore` | 内存实现 + 固定 Parquet 快照，单测不起容器 |
| `DataSource` | fixture 录制响应（含限流/半包/空数据），不依赖网络 |
| `execution` | 手工构造 5 日小 universe（一字板、停牌、退市、除权、零股）逐断言 |
| `performance` | 与独立 SQL/numpy 实现双跑，容差 1e-6 |
| `lookahead_guard` | 变异测试：故意注入未来窗口读取，必须 FAIL |
| `reconcile` | 构造 1bp/5bp 差异，验证是否逐单定位而非抹平 |
