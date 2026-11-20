-- quant-pro DuckDB schema（P1 运行态；TimescaleDB 等价 DDL 见 DETAILED-DESIGN §2）
-- 口径纪律：原始价为准，连续价由 adj_factor 计算；行情只追加，修正另记。

CREATE SEQUENCE IF NOT EXISTS seq_issue START 1;
CREATE SEQUENCE IF NOT EXISTS seq_amend START 1;
CREATE SEQUENCE IF NOT EXISTS seq_order START 1;

CREATE TABLE IF NOT EXISTS instrument (
    symbol        VARCHAR PRIMARY KEY,
    name          VARCHAR,
    exchange      VARCHAR,
    board         VARCHAR,
    industry_l1   VARCHAR,
    list_date     DATE,
    delist_date   DATE,
    is_st         BOOLEAN DEFAULT FALSE,
    total_share   DOUBLE,
    float_share   DOUBLE
);

CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date DATE PRIMARY KEY,
    is_open    BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_bar (
    ts           DATE NOT NULL,
    symbol       VARCHAR NOT NULL,
    open         DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, pre_close DOUBLE,
    volume       BIGINT,                 -- 股
    amount       DOUBLE,                 -- 元
    adj_factor   DOUBLE,                 -- 后复权累积因子，基准=上市日
    float_share  DOUBLE,                 -- 日频流通股本（换手率反推，PIT 市值口径）
    limit_up     DOUBLE,
    limit_down   DOUBLE,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    is_final     BOOLEAN NOT NULL DEFAULT TRUE,
    source       VARCHAR NOT NULL,
    fetched_at   TIMESTAMP NOT NULL,
    data_version VARCHAR NOT NULL,
    PRIMARY KEY (ts, symbol)
);

CREATE TABLE IF NOT EXISTS index_bar (
    ts         DATE NOT NULL,
    index_code VARCHAR NOT NULL,
    close      DOUBLE,
    amount     DOUBLE,
    data_version VARCHAR,
    PRIMARY KEY (ts, index_code)
);

CREATE TABLE IF NOT EXISTS factor_value (
    ts        DATE NOT NULL,
    symbol    VARCHAR NOT NULL,
    factor_id VARCHAR NOT NULL,
    value     DOUBLE,
    PRIMARY KEY (ts, symbol, factor_id)
);

CREATE TABLE IF NOT EXISTS factor_meta (
    factor_id VARCHAR PRIMARY KEY,
    name      VARCHAR,
    direction SMALLINT,
    deps      VARCHAR,
    enabled   BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS backtest_run (
    run_id         VARCHAR PRIMARY KEY,
    strategy_id    VARCHAR,
    version        VARCHAR,
    start_date     DATE,
    end_date       DATE,
    universe       VARCHAR,
    initial_capital DOUBLE,
    cost_model     VARCHAR,
    benchmark      VARCHAR,
    config_hash    VARCHAR,
    seed           INTEGER,
    data_version   VARCHAR,
    status         VARCHAR,
    error          VARCHAR,
    lookahead_status VARCHAR,
    metrics        VARCHAR,
    checklist      VARCHAR,
    created_at     TIMESTAMP,
    finished_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_order (
    order_id      BIGINT PRIMARY KEY,
    run_id        VARCHAR,
    ts            DATE,
    exec_date     DATE,
    symbol        VARCHAR,
    side          VARCHAR,
    req_qty       BIGINT,
    filled_qty    BIGINT,
    price         DOUBLE,
    gross         DOUBLE,
    fee           DOUBLE,
    status        VARCHAR,
    reject_reason VARCHAR
);

CREATE TABLE IF NOT EXISTS backtest_equity (
    run_id   VARCHAR NOT NULL,
    ts       DATE NOT NULL,
    nav      DOUBLE,
    cash     DOUBLE,
    mv       DOUBLE,
    exposure DOUBLE,
    turnover DOUBLE,
    fee      DOUBLE,
    PRIMARY KEY (run_id, ts)
);

CREATE TABLE IF NOT EXISTS backtest_position (
    run_id VARCHAR NOT NULL,
    ts     DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    qty    BIGINT,
    sellable_qty BIGINT,
    cost   DOUBLE,
    adj_cost DOUBLE,
    mv     DOUBLE,
    weight DOUBLE,
    PRIMARY KEY (run_id, ts, symbol)
);

CREATE TABLE IF NOT EXISTS data_issue (
    id        BIGINT PRIMARY KEY,
    ts        DATE,
    symbol    VARCHAR,
    field     VARCHAR,
    kind      VARCHAR,
    detail    VARCHAR,
    blocking  BOOLEAN,
    status    VARCHAR DEFAULT 'open',
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_amendment (
    id        BIGINT PRIMARY KEY,
    ts        DATE,
    symbol    VARCHAR,
    field     VARCHAR,
    old_value VARCHAR,
    new_value VARCHAR,
    reason    VARCHAR NOT NULL,
    actor     VARCHAR NOT NULL,
    marked_stale BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_run (
    job_id     VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    attempt    INTEGER NOT NULL,
    status     VARCHAR,
    rows_affected BIGINT,
    error      VARCHAR,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    idempotency_key VARCHAR UNIQUE,
    PRIMARY KEY (job_id, trade_date, attempt)
);

CREATE TABLE IF NOT EXISTS recon_check (
    run_id VARCHAR NOT NULL,
    ts     DATE NOT NULL,
    expected DOUBLE,
    actual   DOUBLE,
    diff_bp  DOUBLE,
    traced   VARCHAR,
    status   VARCHAR,
    PRIMARY KEY (run_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_bar_symbol ON daily_bar(symbol);
CREATE INDEX IF NOT EXISTS idx_factor_id ON factor_value(factor_id);
CREATE INDEX IF NOT EXISTS idx_issue_kind ON data_issue(kind);

-- ---------------------------------------------------------------- P2：风控 / 信号 / 模拟盘
CREATE SEQUENCE IF NOT EXISTS seq_risk_event START 1;

CREATE TABLE IF NOT EXISTS risk_rule (
    rule_id   VARCHAR PRIMARY KEY,
    name      VARCHAR,
    metric    VARCHAR,
    op        VARCHAR,
    threshold DOUBLE,
    action    VARCHAR,
    priority  INTEGER,
    enabled   BOOLEAN DEFAULT TRUE,
    version   INTEGER DEFAULT 1,
    scope     VARCHAR DEFAULT '*'
);

CREATE TABLE IF NOT EXISTS risk_event (
    id         BIGINT PRIMARY KEY,
    trade_date DATE,
    account_id VARCHAR,
    rule_id    VARCHAR,
    symbol     VARCHAR,
    metric     VARCHAR,
    value      DOUBLE,
    action     VARCHAR,
    status     VARCHAR DEFAULT 'open',      -- open / acked / cleared
    acked_by   VARCHAR,
    acked_at   TIMESTAMP,
    reason     VARCHAR,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signal_run (
    run_id        VARCHAR PRIMARY KEY,
    trade_date    DATE,
    strategy_id   VARCHAR,
    version       VARCHAR,
    status        VARCHAR,                  -- draft / published / superseded / withdrawn
    reason        VARCHAR,
    checks        VARCHAR,
    source_run_id VARCHAR,
    created_by    VARCHAR,
    created_at    TIMESTAMP,
    published_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signal_item (
    run_id         VARCHAR NOT NULL,
    symbol         VARCHAR NOT NULL,
    target_weight  DOUBLE,
    current_weight DOUBLE,
    delta          DOUBLE,
    attribution    VARCHAR,
    PRIMARY KEY (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS paper_account (
    account_id      VARCHAR PRIMARY KEY,
    name            VARCHAR,
    initial_capital DOUBLE,
    cost_model      VARCHAR,
    strategy_id     VARCHAR,
    start_date      DATE,
    status          VARCHAR DEFAULT 'active',
    created_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_order (
    order_id        BIGINT PRIMARY KEY,
    account_id      VARCHAR,
    signal_run_id   VARCHAR,
    ts              DATE,
    exec_date       DATE,
    symbol          VARCHAR,
    side            VARCHAR,
    req_qty         BIGINT,
    filled_qty      BIGINT,
    price           DOUBLE,
    gross           DOUBLE,
    fee             DOUBLE,
    status          VARCHAR,
    reject_reason   VARCHAR,
    idempotency_key VARCHAR UNIQUE
);

CREATE TABLE IF NOT EXISTS paper_equity (
    account_id VARCHAR NOT NULL,
    ts         DATE NOT NULL,
    nav        DOUBLE,
    cash       DOUBLE,
    mv         DOUBLE,
    exposure   DOUBLE,
    turnover   DOUBLE,
    fee        DOUBLE,
    PRIMARY KEY (account_id, ts)
);

CREATE TABLE IF NOT EXISTS paper_position (
    account_id   VARCHAR NOT NULL,
    ts           DATE NOT NULL,
    symbol       VARCHAR NOT NULL,
    qty          BIGINT,
    sellable_qty BIGINT,
    cost         DOUBLE,
    mv           DOUBLE,
    weight       DOUBLE,
    PRIMARY KEY (account_id, ts, symbol)
);

CREATE TABLE IF NOT EXISTS paper_ledger (
    id         BIGINT PRIMARY KEY,
    account_id VARCHAR,
    ts         DATE,
    kind       VARCHAR,
    symbol     VARCHAR,
    qty        BIGINT,
    amount     DOUBLE,
    ref        VARCHAR,
    created_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_risk_event_status ON risk_event(status);
CREATE INDEX IF NOT EXISTS idx_signal_date ON signal_run(trade_date);
