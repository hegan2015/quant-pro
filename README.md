# quant-pro · A股日线智能量化系统

数据接入 → 因子 → 策略 → 回测 → 绩效归因 → 未来函数门禁 → 每日信号 → 模拟盘 → 风控。
当前进度：**P1 内核已跑通真实数据并通过一键验收**（65 条用例全绿、5 项未来函数门禁 pass、
全 A 日线 1014.8 万行入库、三条基线出可信数字）。P2 服务化与控制台待做。

| 文档 | 用途 |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | 需求规格：角色、FR 编号需求、非功能、风险 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构设计：C4 图、双存储、ADR、容量 |
| [DETAILED-DESIGN.md](DETAILED-DESIGN.md) | 详细设计：DDL、协议、撮合伪代码、公式、API |
| [UI-DESIGN.md](UI-DESIGN.md) | 生产侧 UI 规范 + 高保真视觉稿索引 |
| [TEST-ACCEPTANCE.md](TEST-ACCEPTANCE.md) | 测试与验收：用例、红线、一键验收 |

## 快速开始（无需 Docker）

```bash
bash scripts/start.sh                  # 探测 Python 3.12 → venv → 依赖 → 自检
.venv/bin/python scripts/fetch_pilot.py  # 18 只小样本（含退市/停牌/北交所/高分红），几分钟
.venv/bin/python scripts/fetch_all.py    # 全 A 日线 2016–2025，实测 32.35 分钟，可断点续传
bash scripts/verify.sh                 # 一键验收：单测 + 口径自检 + 三条基线回测 + 报告
bash scripts/verify.sh --fast          # 跳过成本敏感性（快 3 倍）
```

行情落在 `data/mkt.duckdb`（DuckDB 进程内库，无服务、无端口，**不需要 Docker**）。
验收产物在 `data/reports/accept-*.md|json` 与 `backtest-run-*.html|json|csv`。
接入 TimescaleDB 后走同一 `MarketStore` 接口，业务代码不变（见 ARCHITECTURE §9）。

## CLI（P1 运行态）

```bash
.venv/bin/python -m app.cli.main status             # 数据水位与自检
.venv/bin/python -m app.cli.main factor             # 计算并落库 7 个内置因子
.venv/bin/python -m app.cli.main evaluate mom_20    # IC / ICIR / 分层 / 相关性
.venv/bin/python -m app.cli.main backtest s2_multifactor --top-n 30   # 回测 + 门禁 + 体检 + 报告
.venv/bin/python -m app.cli.main runs               # 历史回测
```

## 已实现（运行态，可真实执行）

| 能力 | 入口 | 说明 |
|---|---|---|
| 全 A 日线 + 后复权因子 + 涨跌停 + 流通股本 | `scripts/fetch_all.py` / `core/datasource/eastmoney.py` | 东财原始价与后复权价双取，因子由比值归一 |
| 交易日历 / 历史样本池（含退市） | `core/market/calendar.py`、`store.universe(as_of)` | 指数日线为日历源 |
| 数据质量校验 | `core/data/quality.py`（`quant quality`） | 10 类校验，阻断项可拦下游 |
| 7 个内置因子 + 截面处理链 + IC 评估 | `core/factor/`（`quant factor` / `quant evaluate`） | IC 向量化，与 SQL 平均秩实现逐值一致 |
| 3 条基线策略 | `core/strategy/builtin.py` | S1 双均线择时、S2 多因子月度、S3 行业轮动 |
| 撮合内核（整手/T+1/一字板/停牌/退市清算/成本） | `core/engine/execution.py` | 回测与模拟盘共用（FR-P-07） |
| 未来函数门禁 5 项 | `core/engine/lookahead_guard.py` | LAG-1/3/4/5 实跑，LAG-2 因未接财务源标 skipped |
| 绩效与归因 + 离线报告 | `core/performance/`（`quant backtest`） | 单文件 HTML（内联 SVG，无 CDN）+ JSON + CSV |
| 高保真视觉稿 | `prototype/pages/*.html`（`prototype/shoot.py` 出图） | 20 页可点击，数字为演示占位 |

## 尚未实现（P2/P3，不要当作可用）

FastAPI 服务与控制台页面、每日信号发布流、模拟盘账户与逐日对账、风控规则引擎界面、
LLM 研究台与沙箱、TimescaleDB 主存、调度与告警。

## 口径要点（结论可信度依赖这些）

- **复权**：东财后复权是**差额法**（分红按金额加回，`hfq ≈ a + b·raw`），因此
  「后复权因子单调不减」的常见假设不成立；净值用连续价，撮合与整手用真实价，
  分红通过 `(r_adj − r_price)` 计提进现金，**只计一次**（`core/selftest.py` 有断言）。
- **成交时点**：T 日收盘出信号 → T+1 开盘成交；不提供「用 T 收盘价成交」。
- **可交易性**：停牌、一字涨停买不进、一字跌停卖不出、ST/次新禁买、现金不足，
  全部留痕 `backtest_order.reject_reason`，不静默丢弃。
- **退市/长期停牌**：按最后可得价强制清算（`STALE_VALUATION` / `DELISTED`），
  不用陈旧价长期估值——这是 LAG-5 门禁项。
- **换手**：单边成交额 / 平均资产 / 年数。
- **成本**：佣金万 2.5（最低 5 元）+ 印花税卖出千 0.5 + 过户费 0.01bp + 滑点 5bp，
  并强制输出 0/5/10bp 三档敏感性。

## 三条基线的真实结论（不修饰）

| 策略 | 全期年化 | OOS Sharpe | 最大回撤 | 体检 |
|---|---|---|---|---|
| S1 双均线择时 × 流动性 50 | -7.61% | -0.54 | -65.2% | FAIL |
| S2 多因子月度 Top30 | +3.39% | +0.07 | -44.9% | FAIL |
| S3 行业轮动 | -6.85% | -0.79 | -61.7% | FAIL |

三条都是**引擎验收件**（验证撮合/择时仓位/约束/行业/成本/退市清算路径），链路全绿但**没有一条通过过拟合体检**，
按 FR-A-04 不得进入信号发布与模拟盘。要拿到可用于决策的数字，需要接入财务 PIT 因子、
做因子集筛选与稳健性验证（P3 研究台），而不是调低成本假设或缩短留出区间。

## 已知限制（如实声明）

1. 免费源不含 PIT 财务数据 → 估值/质量类因子未实现，LAG-2 门禁 skipped（A-02）。
2. 样本池按窗口起点前 250 日流动性挑选 3000 只（`universe_size=1000` 时），
   非全 A 等权；面板内存约 672 MB，全 A 需显式放大并承受耗时。
3. 行业分类来自东财当前快照（5584/5931 有值），退市标的多为空 → S3 覆盖面受限。
4. 归因目前只有单票贡献与行业暴露，Brinson 需基准成分权重（未接入）。
5. 双源比对（同花顺）与断点续传的自动化用例尚未补齐（见 TEST-ACCEPTANCE §11.1）。
6. 模拟盘、信号发布、风控界面、API 鉴权属 P2；AI 研究台与沙箱属 P3。
7. 基线回测用 1000 万初始资金：1M 时「目标金额不足一手」会让篮子系统性偏向低价股
   （实测占 37% 次拒单），该情形现已作为 `LOT_TOO_LARGE` 留痕而非静默丢弃。
8. 输出为研究结论，不构成投资建议；系统不连接券商实盘通道。
