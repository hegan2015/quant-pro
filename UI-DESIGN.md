# 智能量化系统 UI 设计说明书（UI-DESIGN，生产侧）

| 项 | 值 |
|---|---|
| 项目代号 | quant-pro |
| 文档版本 | v0.1（对应 [REQUIREMENTS](REQUIREMENTS.md) FR-U / [DETAILED-DESIGN](DETAILED-DESIGN.md) §16 / [TEST-ACCEPTANCE](TEST-ACCEPTANCE.md) §3.8） |
| 编制日期 | 2026-11-20 |
| 定位 | **生产侧运行态规范**：定义真实交付的 Vue 3 + Element Plus 实现基线，不是演示稿。原型与运行态对照见 §15 |
| 生效条件 | 前端改动需 `npm run build` 产出 `dist/` 并由 8101 静态服务加载才生效；后端改动需重启 api(:8102)/worker 进程。文档中的「运行态」= 已通过 §16 走查 + TC-U 用例的真实页面 |

---

## 1 设计目标与原则

| 编号 | 原则 | 界面落点 |
|---|---|---|
| UI-01 | **数字即口径**：任何数字能一眼看到公式与数据水位 | 指标值 hover 显示口径气泡（公式 + 区间 + `data_version` 后 6 位） |
| UI-02 | **服务端判定，界面只呈现** | 门禁/风控/发布校验结果来自 API 字段，前端不复算、不自行放宽；状态为 `FAIL` 时按钮真实禁用（由响应驱动，非硬编码） |
| UI-03 | **异常必须可见** | 拒单、缺数、对账差异、作业 PARTIAL 全部有默认展示的入口与计数徽标，禁止藏在二级页 |
| UI-04 | **长任务可见可取消** | 回测/抓取有进度、耗时、可取消；离开页面不丢任务（后台 job + 通知） |
| UI-05 | **不可逆动作有阻力** | 发布信号、重放账本、解除熔断、数据修正 → 二次确认 + 原因必填 + 操作人留痕 |
| UI-06 | **密度优先的金融表格** | 默认紧凑行高（32px）、tabular-nums、列固定与冻结首列、虚拟滚动 ≥ 2000 行 |
| UI-07 | **键盘与可达性** | 全操作可键盘完成，焦点可见，色盲安全（涨跌双编码） |
| UI-08 | **每个能力都有界面入口** | 凡 API 提供的运营/管理能力必须进管理台对应页面；仅有 API 无 UI 的项在 §14 显式标注期次，不允许「隐身能力」 |

---

## 2 设计令牌（Design Tokens）

运行时以 CSS 变量落地（`tokens.css`），Element Plus 主题变量从其映射；组件禁止写死色值/间距（设计走查项）。

### 2.1 色板

| 语义 | Token | 值 | 用途 |
|---|---|---|---|
| 主色 | `--brand-600` | `#0F4C81` | 导航激活、主按钮、链接 |
| 主色浅 | `--brand-100` | `#E8F0FE` | 选中底色、信息条 |
| 涨（**A股惯例=红**） | `--market-up` | `#D6453D` | 正收益、涨幅、买入标记 |
| 跌（**A股惯例=绿**） | `--market-down` | `#1F9254` | 负收益、跌幅、卖出标记 |
| 平 | `--market-flat` | `#8A93A2` | 0 或无变动 |
| 成功 | `--ok-600` | `#2F8540` | 校验通过、作业成功（与「跌」区分：不用于行情） |
| 警告 | `--warn-600` | `#B26A00` | PARTIAL、口径降级、WARN 体检项 |
| 危险 | `--err-600` | `#B33771` | 门禁 FAIL、熔断、拒单、对账超阈 |
| 信息 | `--info-600` | `#3B6FD4` | 提示、中性状态 |
| 文本 | `--text-1/2/3` | `#1A1D22 / #545C68 / #8A93A2` | 主/次/辅 |
| 背景 | `--bg-0/1/2` | `#FFFFFF / #F5F7FA / #EDEFF3` | 页面/卡片/分隔 |
| 边框 | `--line-1/2` | `#E3E7ED / #CDD4DE` | 常规/强调分隔 |
| 图表序列 | `--chart-1..8` | `#0F4C81,#B26A00,#2F8540,#B33771,#3B6FD4,#7A5AF8,#0FA3A3,#6B7280` | 多策略对比固定序，跨页一致 |

> **涨跌色约定是硬要求**：默认中国市场「红涨绿跌」，可在系统设置切为国际（绿涨红跌），切换后全端一致。**色盲安全**：涨跌除颜色外必须带符号与箭头（`+3.21%▲` / `-1.08%▼`），颜色不可作为唯一编码（UI-07，走查项）。

### 2.2 排版 / 间距 / 形状 / 层级 / 断点

| 类别 | Token | 值 |
|---|---|---|
| 字体 | `--font-ui` | `-apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif` |
| 数值字体 | `--font-num` | `"JetBrains Mono", "SF Mono", ui-monospace, monospace`；启用 `font-variant-numeric: tabular-nums` |
| 字号 | `--fs-xs/sm/base/lg/xl/2xl` | `12 / 13 / 14 / 16 / 20 / 24`（表格正文 13，指标卡 20） |
| 行高 | `--lh-tight/normal` | `1.25 / 1.5` |
| 间距基数 | `--sp-1..8` | `4 / 8 / 12 / 16 / 24 / 32 / 48`（卡片内 16，卡片间 16，页面 24） |
| 圆角 | `--r-sm/md` | `4 / 8`（卡片 8、按钮/输入 4、图表卡 8） |
| 阴影 | `--sh-1/2` | `0 1px 2px rgba(16,24,40,.06)` / `0 4px 16px rgba(16,24,40,.10)`（弹层 2） |
| 层级 | `--z-nav 100 / --z-dropdown 500 / --z-modal 900 / --z-toast 1000` | 抽屉与 Modal 不叠加超过 2 层 |
| 断点 | `--bp-sm 768 / --bp-md 1024 / --bp-lg 1280 / --bp-xl 1440` | 1440 为设计基准宽；<1024 侧栏自动折叠；<768 只读模式（不做移动端研究操作） |
| 密度 | `--row-h-compact 32px / --row-h-default 40px` | 研究表格默认紧凑，可在系统设置切默认 |

### 2.3 暗色模式

v0.1 提供 `data-theme="dark"` 令牌集（背景 `--bg-0 #12161C`、文本 `#E6EAF0`、图表降饱和 15%），默认跟随系统，**P3 交付**；亮/暗切换不改涨跌色语义。

---

## 3 信息架构与导航

### 3.1 两级菜单（按业务域分组）

```
概览            /dashboard                 总览驾驶舱
数据            /data/quality              数据质量看板
                /data/amendments           修正留痕
                /data/sources              双源比对与差异
                /data/jobs                 作业与水位
研究            /research/factors          因子库（IC/分层/相关性）
                /research/strategies       策略与版本
                /research/ai-lab           AI 研究台（沙箱 + 体检）
回测            /backtest/new              发起回测
                /backtest/runs             回测记录
                /backtest/compare          多列对比
信号            /signals/today             当日信号与发布
                /signals/history           历史信号（含撤回）
模拟盘          /paper/accounts            账户
                /paper/positions           持仓与流水
                /paper/orders              订单与拒单
                /paper/reconciliation      对账与差异追溯
                /paper/replay              账本重放
风控            /risk/rules                规则与阈值
                /risk/events               风控事件与确认
                /risk/circuit-breaker      熔断状态与解除
系统            /system/config             参数与口径配置
                /system/users              角色与令牌
                /system/audit              审计日志
```

侧栏分组可折叠并记忆状态；每组右侧计数徽标：数据组=阻断 issue 数，模拟盘组=未确认 `recon_diff` 数，风控组=`risk_event(open)` 数（UI-03）。

### 3.2 角色 × 菜单可见性

| 菜单组 | viewer | researcher | pm | data | risk |
|---|---|---|---|---|---|
| 概览 / 数据（只读部分）/ 回测记录 | 可见 | 可见 | 可见 | 可见 | 可见 |
| 研究（含 AI 研究台） | 可见（只读） | **可操作** | 可见 | 可见 | 可见 |
| 发起回测 | 隐藏 | **可用** | 可用 | 隐藏 | 隐藏 |
| 信号发布/撤回 | 隐藏 | 生成草稿 | **可用** | 隐藏 | 隐藏 |
| 模拟盘操作（下单/重放） | 只读 | 只读 | **可用** | 隐藏 | 只读 |
| 数据补数/修正 | 隐藏 | 隐藏 | 隐藏 | **可用** | 隐藏 |
| 风控规则/事件/熔断 | 只读 | 只读 | 只读 | 只读 | **可用** |
| 系统配置/审计 | 隐藏 | 隐藏 | 只读 | 只读 | 只读 |

不可见的入口**不渲染**（而非置灰诱导点击），直接访问路由返回 `403` 组件（TC-U-10）。

### 3.3 顶栏与环境标识

`LOGO + 环境标记（dev / local / prod 胶囊，prod 为红色描边）| 数据水位（最新交易日 + 缺口天数 + store 模式 Timescale/DuckDB-降级）| 搜索（标的/策略/运行 ID）| 通知 | 用户与角色 | 退出`

数据水位是全局组件：DuckDB 降级时显示 `--warn-600` 徽标并 tooltip 说明原因；缺口 > 0 时点击直跳 `/data/jobs`。

---

## 4 页面规格

统一结构：`PageHeader(标题+口径说明+操作区) → 筛选区(FilterBar) → 内容网格 → PageFooter 免责声明`。

### 4.1 `/dashboard` 总览驾驶舱（FR-U-01）

| 分区 | 内容与组件 | 数据源 |
|---|---|---|
| KPI 条（4 卡） | 组合净值、当日收益、最大回撤、超额(vs 000300)；每卡：值 + 环比 + 口径气泡 + 更新时间 | `GET /paper/accounts/{active}` + `.../reconciliation?range=1d` |
| 主图 | `NavChart`（净值 vs 基准双轴叠加 `DrawdownChart` 副轴），区间切换 1M/3M/YTD/3Y/全部，悬停十字线显示当日持仓前 5 | `GET /backtests/{id}/equity?freq=` |
| 今日信号卡 | 状态徽章（draft/published/none）、换手、主要增仓 Top3 / 减仓 Top3、「查看完整信号」 | `GET /signals?trade_date=today` |
| 风控状态 | 熔断进行中横幅（`--err-600`）+ 未确认事件数 + 回撤水位进度条 | `GET /risk/events?status=open` |
| 数据与健康 | 最新交易日、覆盖率、阻断 issue 数、最近 5 次作业（状态色点） | `GET /healthz` + `GET /jobs?trade_date=` |
| 待办（右栏） | 按角色生成：pm=未发布信号/对账差异；researcher=体检未过策略；risk=待确认事件；data=缺口 | 各 API 聚合 |

状态矩阵：无账户→引导创建（只 pm 显示按钮）；数据未就绪→KPI 显示 `--` + 「数据水位」tooltip + 补数入口；作业失败→红条横幅附 `trace_id` 复制。

### 4.2 `/data/*` 数据中心（FR-U-02、FR-U-03）

- **quality**：顶部汇总卡（行数/覆盖率/阻断项/异常类型分布饼）+ 明细表（列：交易日、标的、字段、类型 `kind`、详情、阻断、状态、操作）。操作：`标记 ignored`（需理由，`role:data`）、`查看原值`（双源对照抽屉）。支持按 `kind/blocking/symbol` 筛选，默认展示 blocking 项。
- **amendments**：只追加流水表（原值、新值、理由、操作人、时间、stale 标记）。「相关回测标 stale」列可跳转受影响 run_id 列表；**页面不提供任何直接编辑行情的入口**（ADR-013）。
- **sources**：双源比对表（东财 vs 同花顺，标的×日期×字段），差异率汇总、超阈值行高亮，可导出 CSV 供人工核。
- **jobs**：作业列表（`job_id/交易日/状态/行数/耗时/错误`）+ 详情抽屉（attempt 时间线、缺口清单、断点续传进度）。`触发补数` 按钮（`role:data`）带 `force` 复选与影响说明；上游 PARTIAL 时下游行显示 `SKIPPED_UPSTREAM` 灰标并可展开因果链。

### 4.3 `/research/*` 研究（FR-U-03、FR-F、FR-A）

- **factors**：主表（因子、方向、窗口、IC均值、ICIR、t值、IC>0占比、Top-Bottom 年化、5 分层单调标记、最大相关、状态徽标 启用/待确认/已失效）。点行进详情：`ICSeriesChart` + `QuantileBar`（5 层柱，单调性不满足标 `--warn-600`）+ `CorrelationMatrix`（热力，>0.95 单元格标红并提示 FR-F-05 确认）+ 依赖图。操作：`重算评估`（窗口选择）、`注册新因子`（走 AI 研究台或代码导入）。
- **strategies**：策略卡（id、名称、版本链、最近 3 次回测摘要、体检结论）；版本对比抽屉（参数 diff + 关键指标 diff）。
- **ai-lab**：会话式三区（左：需求与口径澄清问答；中：生成的代码草稿 + 静态检查结果列表；右：沙箱运行输出、错误回显、体检表）。硬约束在界面体现：无「直接下单/改阈值」类控件；沙箱违规显示 `SandboxViolation` 红卡与命中规则；体检 FAIL 时注册按钮禁用并列出命中红线（TC-A-05、UI-02）。

### 4.4 `/backtest/new` 与运行详情（FR-U-04、FR-B）

表单（由策略 `params_schema` 动态渲染，两列 + 分组：区间与宇宙 / 成本 / 基准 / 风控与约束 / 随机种子）：

| 控件 | 校验 | 生产注意 |
|---|---|---|
| 起止日期（交易日历） | 非交易日自动顺延并提示实际调仓日 | 显示实际展开的调仓次数 |
| universe | `ALL_A / 300+500 / 自定义列表` | 选 ALL_A 时显示预估耗时与「首次导入数据」前置检查（缺数则给补数链接） |
| 成本项 | 佣金/印花税/过户/滑点 bp | 滑点旁固定标注「敏感性将自动跑 0/5/10bp」 |
| 样本外区间 | 默认 2022–2025 留出 | 训练/留出重叠时禁止提交 |

运行页：进度条（已处理交易日 n/total + ETA + 取消）→ 完成后五组指标卡（收益/风险/比值/交易/基准与结构，缺项显示 `N/A + 原因`）→ `NavChart`/`MonthlyHeatmap`/`AttributionBar`(Brinson) → 成本敏感性小表（三档并排，随滑点非单调时自动标红）→ **未来函数门禁面板**（5 项 LAG 检查逐条 pass/FAIL + 详情）→ **体检表面板**（红线表，FAIL 项说明命中阈值）→ 拒单分析（按 `reject_reason` 分布 + 明细跳转）→ 报告下载（HTML/JSON/CSV）。

发布相关联动：`lookahead_status=FAIL` 或体检 FAIL 时，「转信号发布」按钮由 API 字段驱动禁用，并显示禁用原因 tooltip（TC-U-05）。

### 4.5 `/signals/today` 信号与发布（FR-G）

布局：顶部校验面板（4 项前置：新鲜度/阻断 issue/门禁/风控预检，每项 pass/FAIL + 说明）→ 目标组合表（标的、目标权重、当前权重、Δ、方向箭头、归因分解展开、可交易性标记）→ 换手摘要（单边/双边、预估成本）→ 操作区。

发布流（`role:pm`）：`发布` → `ConfirmDialog`（显示权重合计、换手、成本预估、风控命中预览 + 需勾选「我已确认口径」）→ 成功 `published` 后表格只读锁 + 可撤回（原因必填）。任一前置 FAIL：面板红、按钮禁用、给出逐项修复链接（如跳 `/data/jobs` 或该 run 的门禁详情）——对应 TC-G-01。

### 4.6 `/paper/*` 模拟盘（FR-P，最严格的数字页）

- **positions**：持仓表（标的、数量、可售数量（T+1 列，不可卖显示 `0/1200` 形态）、成本、连续成本、市值、浮动盈亏、权重、行业）+ 资产摘要条（现金/总资产/暴露/当日盈亏/净值）。表底必须显示 `现金 = Σ流水` 一致性指示（绿=相等，红=不等并跳对账）。
- **orders**：全部订单，`status` 色彩语义（filled=ok、rejected=err、partial=warn），拒单行内直接展示中文可读原因（映射 §错误码，如「一字涨停无法买入」）+ 原始码 tooltip。筛选默认 `仅看异常`。
- **reconciliation**：逐日 `diff_bp` 折线（阈值 1bp 参考线，超限点红）+ 差异明细表（expected/actual/diff/状态）+ **追溯抽屉**（`traced` 逐单链路：哪笔订单/哪类费用/是否估值沿用，时间线形式）。页面明确不提供「手工调整」输入（TC-P-06）；只有「重放验证」按钮。
- **replay**：危险操作页——表单（起始日、账户、副本命名）+ 影响说明（原账本零写入、生成 `-replay-<ts>` 新账户）+ 二次确认 + 结果页给出新旧 digest 对比证明未污染原账本。

### 4.7 `/risk/*` 风控（FR-R）

- **rules**：规则表（id、指标、比较符、阈值、动作、优先级、启用、版本）+ 行内编辑（`role:risk`，保存即弹原因与前后值 diff，落 `app_config` 审计）；内置规则可停用不可删。
- **events**：事件列表（交易日、账户、规则、指标值、动作、状态、操作人）+ 详情抽屉（触发时快照：净值曲线片段、持仓 Top、规则参数）+ `确认(ack)`（原因 + 操作人自动带出）；`open` 数在侧栏徽标与全局通知同步。
- **circuit-breaker**：醒目横幅态（进行中=全页红顶条 + 「仅拒绝新增买入，不强平」说明）+ 水位期内峰值回撤进度 + 解除面板（仅 `role:risk`，需填解除理由与复核结论）+ 熔断期间被拒订单清单。

### 4.8 `/system/*`（FR-O、安全）

配置项表单（口径类只读展示 + 可配项编辑带影响提示：改 `RF_ANUMAL`/`COST_*` 会标记历史 run 口径差异）、密钥状态检查（只显路径与权限位，**不回显口令值**）、角色与令牌管理、审计日志检索（actor/action/target/before/after/时间）。

---

## 5 组件库存量表

| 组件 | 职责 | 关键 props | 复用页 | 生产细节 |
|---|---|---|---|---|
| `MetricCard` | 指标 + 环比 + 口径气泡 | `value, delta, formula, dataVersion, tone` | dashboard/backtest | 数字用 `--font-num`；`N/A` 必带原因 |
| `NavChart` | 净值/基准/回撤组合图 | `series[], benchmark, drawdown, range` | dashboard/backtest/paper | Chart.js + 自绘十字线；≥5000 点降采样(LTTB) 并在 tooltip 标注「已降采样」 |
| `MonthlyHeatmap` | 月度收益矩阵 | `matrix, yoyCol` | backtest | 色阶用 `--market-up/down` 淡变；0 显示 `—` |
| `QuantileBar` | 5 分层年化 | `bars, monotonic` | research | 非单调自动标注 |
| `CorrelationMatrix` | 因子相关性热力 | `matrix, threshold` | research | >0.95 单元格红框 + 提示 |
| `OrderTable` | 订单/拒单 | `rows, focusRejected` | backtest/paper | 虚拟滚动；原因双列（中文 + 码） |
| `ReconDiffList` | 对账差异 + 追溯 | `rows, traceOf` | paper | 阈值参考线、无编辑入口 |
| `RiskEventDrawer` | 事件详情与确认 | `event, canAck` | risk/dashboard | 快照内嵌迷你净值图 |
| `JobProgress` | 作业/回测进度 | `jobId, status, eta` | data/backtest | 可取消；指数退避轮询 1→5s，5min 上限 |
| `ParamForm` | schema 驱动表单 | `schema, values` | backtest/strategies | 字段级校验 + 提交前口径摘要 |
| `GatePanel` | 门禁/体检 | `checks[]` | backtest/signals/ai-lab | 全量展示，不因通过而隐藏 |
| `ConfirmDialog` | 危险操作 | `summary, requireReason, checkbox` | signals/paper/risk | 确认文案含影响数字，非泛化「确定吗」 |
| `EmptyState` / `PageForbidden` / `ErrorState` | 态组件 | `reason, action` | 全部 | 错误态必须含 `trace_id` 复制按钮 |
| `DisclaimerFooter` | 免责声明 | — | 全部（常驻） | 「研究结论，不构成投资建议；不接实盘」 |

---

## 6 数据可视化规范

| 场景 | 图型 | 规则 |
|---|---|---|
| 净值 vs 基准 | 双折线（主轴）+ 回撤面积（副轴，负向） | 策略=`--chart-1`，基准=`--chart-2` 虚线；回撤半透明 `--market-down` 10% |
| 多策略对比 | 多折线（≤5 条，超出改小倍数） | 序列色固定映射表，跨页一致；图例可点选隐藏，不参与重算刻度 |
| 月度/年度收益 | 热力矩阵 | 收敛色阶（±4% 内），极值不放大 |
| 分层/归因 | 分组柱 + 瀑布（Brinson） | 正 `--market-up` 负 `--market-down`（与符号一致，双编码） |
| 分布/VaR | 直方图 + 分位线 | 5% 分位虚线标注 |
| 相关性 | 对称热力矩阵 | 只渲染上三角，对角隐藏 |

所有图必须：① tooltip 含日期 + 全部序列值 + 单位；②空数据渲染 `EmptyState` 而非空坐标系；③可导出 PNG（图表右上导出菜单）与「复制该组数字」；④不依赖颜色单一编码；⑤移动端降级为表格。

---

## 7 表格、数字与文案格式

| 类型 | 规则 |
|---|---|
| 价格 | 2 位小数，tabular；停牌 `—` |
| 金额 | 千分位；≥1e8 显示「1.23 亿」、≥1e4 显示「12.34 万」（阈值可切「纯数字」模式） |
| 收益率/权重 | 2 位百分数，正数带 `+`；`0` 显示 `0.00%` |
| 差值(bp) | 1 位小数 + 符号；>阈值着色 |
| 数量 | 千分位整数，卖出零股标 `非整手` |
| 日期 | `YYYY-MM-DD`（交易日）；时间戳 `YYYY-MM-DD HH:mm:ss` + 时区标注 `Asia/Shanghai` |
| 空值 | 统一 `—`，并在 tooltip 说明缺失原因（不显示 `null`/`NaN`/`undefined`，走查阻断项） |
| 状态文案 | 中文语义 + 原始码 tooltip（如 `一字涨停无法买入 / LIMIT_UP_ONE_PU`） |
| 排序 | 服务端排序 + 分页默认 50（可选 20/50/200）；>2000 行虚拟滚动 |
| 文案 | 术语与 [REQUIREMENTS §1.4](file:///Users/hegan/Documents/Qoder/quant-pro/REQUIREMENTS.md) 术语表一致；按钮动词开头（发起回测、发布信号、重放账本）；错误文案 = 现象 + 原因 + 下一步 |

---

## 8 交互与状态规范

**加载**：骨架屏（卡片/表格行级）而非整页 spinner；>1.5s 显示「预计 n 秒」；>10s 转后台任务 + 完成通知。
**错误**：4xx 就地提示（字段级 + 顶部横幅两种，禁止只弹 toast 后页面半可用）；5xx/`StoreUnavailable` 显示全局横幅与重试，禁用写操作按钮；所有错误带 `trace_id`。
**并发**：同一 run 重复提交返回 409 → 界面提示「已有进行中的运行，是否跳转查看？」（TC-P-02）。
**长任务离开页面**：不阻断，右上角常驻进度胶囊；完成时通知并高亮结果入口。
**表单**：失焦即校验，提交时全量校验并聚焦首个错误；危险值（如滑点 0、权重上限 >20%）需二次确认提示影响。
**筛选记忆**：URL query 持久化筛选与区间（可分享复现）；研究页的 `config_hash` 出现在 URL 便于回溯（UI-01）。
**通知**：站内信中心 + 可选外发（受 `role` 与开关控制）；对账超阈、熔断、作业连失 3 次为最高优先级。
**审计**：所有写操作成功后返回 `操作人 + 时间 + 记录 ID`，页面显示「已留痕 #id」，不可静默。

---

## 9 无障碍、性能与工程约定

| 维度 | 要求 |
|---|---|
| a11y | WCAG 2.1 AA：对比度正文 ≥4.5:1、大字 ≥3:1（红涨 `#D6453D` on white = 4.6:1 已达标，禁用更浅变体）；键盘 Tab 序按视觉流；焦点环 `2px --brand-600`；表格 `<th scope>` + `aria-sort`；图表提供 `aria-label` 摘要 + 数据表格替代；涨跌符号双编码；`prefers-reduced-motion` 下关闭动画 |
| 性能预算 | 首屏 JS ≤ 300 KB gzip、CSS ≤ 60 KB；路由懒加载；`NavChart` 数据 >5000 点降采样；列表接口分页；首屏 TTI < 2s（本地）；长表虚拟滚动 |
| 工程 | Vue 3 `<script setup>` + TS；Pinia 分域 store（`market/backtest/paper/risk/ui`）；API 客户端由后端 OpenAPI 生成（禁止手写 fetch 漂移）；组件零硬编码色值；ESLint + Stylelint + `tokens.css` 单一来源 |
| 状态与错误边界 | 每个页面必须实现 5 态：正常 / 加载 / 空 / 错误 / 无权限（TC-U-11）；写操作后仅刷新受影响局部数据，避免整页重载丢状态 |
| 部署 | `vite build → dist/`；静态服务 :8101，`/api` 反代 :8102；构建产物带内容哈希；灰度/回滚沿用站点静态资源版本化，改口径字段需前后端同版本发布（生效条件见文档头） |

---

## 10 关键流程时序（UI 视角）

```mermaid
sequenceDiagram
  participant U as 研究员
  participant FE as 控制台
  participant API as api:8102
  U->>FE: 填参 → 发起回测
  FE->>API: POST /backtests（schema 校验通过后）
  API-->>FE: 202 {run_id}
  FE->>FE: JobProgress 轮询（1→5s 退避）
  API-->>FE: GET /backtests/{id} → status/metrics/checklist/lookahead
  FE-->>U: 指标卡 + 门禁面板 + 体检表（FAIL 项红色并锁发布按钮）
  U->>FE: 转信号发布
  FE->>API: POST /signals → draft
  API-->>FE: 前置校验结果（4 项）
  U->>FE: pm 点击发布（二次确认，含数字摘要）
  API-->>FE: published / 422 原因清单
  FE-->>U: 只读锁 + 留痕 #id + 通知模拟盘
```

---

## 11 UI 与后端契约的防漂移约定

1. 所有页面数据字段必须来自 OpenAPI 生成类型，字段缺失时显示 `—` + 「接口未提供」诊断条，不得前端造数。
2. 门禁/体检/风控的「按钮可用性」由响应字段驱动（`can_publish: bool` + `blocking_reasons[]`），前端不重复实现判定逻辑（UI-02、TC-R-08 双保险：绕过 UI 直调 API 服务端仍拒）。
3. 口径展示（公式文本、区间、`data_version`）由后端下发，避免中英/版本漂移。
4. 数字一致性抽查用例（TC-U-02）直接比对 SQL 与页面值，作为发布项。

---

## 12 交付期次与「运营能力必须进 UI」映射

| 能力 | 页面/控件 | 期次 | 说明 |
|---|---|---|---|
| 触发补数 / 断点续传 / `force` | `/data/jobs` 按钮 | P2 | 不得只留 CLI |
| 数据修正留痕 | `/data/amendments` + 新增修正对话框 | P2 | 理由必填 |
| 双源比对查看与导出 | `/data/sources` | P2 | |
| 因子重算评估 / 注册确认（>0.95） | `/research/factors` | P2 | |
| 策略版本管理与 diff | `/research/strategies` | P2 | |
| 发起/取消/对比回测、报告下载 | `/backtest/*` | P1 报告走 CLI+HTML，P2 全进 UI | P1 期间该能力为「仅 API/CLI」，需在此标注 |
| 门禁与体检查看 | `GatePanel` | P1 HTML 报告内，P2 UI | |
| 信号发布/撤回 | `/signals/today` | P2 | 必须带二次确认 |
| 模拟盘账户/订单/对账/重放 | `/paper/*` | P2 | |
| 风控规则编辑 / 事件确认 / 熔断解除 | `/risk/*` | P2 | 仅 `role:risk` |
| AI 研究台（沙箱/体检/注册） | `/research/ai-lab` | P3 | |
| 口径与成本配置 | `/system/config` | P2 | 密钥不回显 |
| 审计日志检索 | `/system/audit` | P2 | |
| 角色与令牌管理 | `/system/users` | P2 | |
| 通知开关 | 顶栏设置 | P2 | |

红线：交付时任何「仅 API/CLI 有、UI 无」的运营能力都必须在发布说明中单列并指明期次，不允许默认隐身（对齐 UI-08）。

---

## 13 走查清单（发布前自检，映射 [TEST-ACCEPTANCE §3.8](file:///Users/hegan/Documents/Qoder/quant-pro/TEST-ACCEPTANCE.md)）

- [ ] 令牌零硬编码：抽查 10 个组件无字面色值/px（`design-debt` 扫描）
- [ ] 涨跌红绿正确且带符号；切换国际配色后全局一致
- [ ] 无 `NaN/null/undefined` 渲染；空值统一 `—` 并有原因
- [ ] 5 态（正常/加载/空/错误/无权限）逐页齐备（TC-U-11）
- [ ] 门禁/体检 FAIL 时发布入口真实禁用，且绕过 UI 服务端仍拒（TC-U-05、TC-R-08）
- [ ] 对账页无任何手工调整输入（TC-P-06）
- [ ] 危险操作均有数字摘要式二次确认 + 原因必填（TC-U-08）
- [ ] 指标 hover 口径气泡含公式与数据水位（UI-01）
- [ ] 键盘可达：Tab 序、焦点环、快捷键（`g d`→dashboard 等）可用
- [ ] 1440/1280/1024/768 四档布局不破版；<768 只读模式生效
- [ ] 首屏体积与 TTI 达预算；万级订单表滚动 ≥50fps
- [ ] 控制台无错误日志、无接口 4xx 残留；`trace_id` 可见可复制
- [ ] 免责声明常驻每页（TC-U-13）
- [ ] UI vs 仅 API 清单（§12）与实际一致，无夸大表述

---

## 14 视觉稿与运行态对照

### 14.1 视觉稿资产（已交付，可点击）

生成器与产物（离线 HTML，无 CDN，图表为内联 SVG）：

```bash
.venv/bin/python prototype/build.py --check   # 生成 20 页 + 脏值自检（TC-X-02）
.venv/bin/python prototype/shoot.py           # 本机 Chrome 无头截图 → prototype/shots/*.png
open prototype/pages/index.html               # 从总览页点击进入各页
```

| 视觉稿页面 | 对应 FR / TC | 截图 |
|---|---|---|
| 总览与组件库 | §2 §5 | ![index](prototype/shots/index.png) |
| 总览驾驶舱 | FR-U-01 / TC-U-02 | ![dashboard](prototype/shots/dashboard.png) |
| 数据质量 | FR-U-02 / TC-D-07 | ![data-quality](prototype/shots/data-quality.png) |
| 作业与水位 | FR-O-01 / TC-O-01 | ![data-jobs](prototype/shots/data-jobs.png) |
| 因子库（IC/分层/相关性） | FR-F-04/05 / TC-F-06/07 | ![factors](prototype/shots/research-factors.png) |
| AI 研究台（沙箱+体检） | FR-A-02/04 / TC-A-02/05 | ![ai-lab](prototype/shots/research-ai-lab.png) |
| 回测发起与运行详情 | FR-U-04 / TC-U-04/05 | ![backtest](prototype/shots/backtest.png) |
| 当日信号与发布 | FR-G-01/02/03 / TC-G-01 | ![signals](prototype/shots/signals.png) |
| 模拟盘持仓与订单 | FR-P-02/03 / TC-B-09 | ![paper](prototype/shots/paper.png) |
| 对账与差异追溯 | FR-P-05 / TC-P-05/06 | ![recon](prototype/shots/paper-recon.png) |
| 风控规则与事件 | FR-R-01/04 / TC-R-07 | ![risk](prototype/shots/risk.png) |
| 熔断状态 | FR-R-03 / TC-R-01 | ![breaker](prototype/shots/risk-breaker.png) |

另有 8 页（修正留痕、双源比对、策略与版本、回测记录、历史信号、账本重放、参数与口径、审计日志）在 `prototype/pages/`，导航可互跳；未单独出图。

### 14.2 视觉走查已修缺陷（真实执行发现，非纸面）

| 缺陷 | 现象 | 修复 |
|---|---|---|
| 数字不同源 | KPI 最大回撤 -21.43% 与图表标注 -23.15% 不一致 | 统一由 `stats_of()` 从同一净值序列计算 |
| 损失类指标误用绿色 | 最大回撤显示为绿（A股绿=跌，但回撤不是收益方向） | 新增 `.neg` 用 `--err-600`；红涨绿跌仅用于收益方向 |
| 统计条溢出重叠 | 年化/Sharpe/回撤/峰谷四项 flex 挤压重叠 | 改 `.stats` 网格 + `.stat` 块级布局 |
| 按钮断行 | 「取消」被挤成两行 | `.btn{white-space:nowrap}` |
| 脏值扫描误报 | 技术标签（如「置 NaN 重跑」）被当脏值 | 扫描范围收敛到表格单元格与 KPI 数值 |

### 14.2b 运行态控制台（P2 已交付，浏览器实测通过）

`app/console/`：Vue 3 全局构建 + Element Plus **本地 vendored**（`vendor/`，离线、无构建步骤），
8 页接真 API：总览 / 数据 / 研究 / 回测 / 信号 / 模拟盘 / 风控 / 系统。
菜单两级分组 + 一级 SVG 图标 + 选中指示条；登录用 dev 令牌（`~/.config/quant-pro/auth.json`，600）。

实测截图（`scripts/ui_smoke.py`，Playwright + Chromium，控制台 0 error）：

| 截图 | 内容 |
|---|---|
| ![dash](data/reports/ui/01-dashboard.png) | 总览：KPI + 最近回测净值 + 熔断横幅 |
| ![data](data/reports/ui/02-data.png) | 数据质量 issue + 作业 + 修正留痕入口 |
| ![signal](data/reports/ui/09-signal-draft.png) | 信号草稿 + 四项前置校验面板 |
| ![pub](data/reports/ui/10-signal-published.png) | 勾选确认后发布 |
| ![recon](data/reports/ui/11-paper-recon.png) | 模拟盘对账（产物级重算，无手工调整入口） |

### 14.3 原型与运行态边界

| 页面 | 视觉稿（可点击 HTML，数字为演示占位） | 运行态（Vue + 真接口） |
|---|---|---|
| 视觉稿 20 页 | ✅ 已交付 | — |
| 运行态控制台 8 页 | — | ✅ P2 已交付并浏览器实测 |
| 生效条件 | 直接打开 HTML | 需 `npm run build` + api(:8102)/worker 运行；未联调页面不得标「运行态」 |

评审纪律：视觉稿用于定版式、口径展示与交互路径；**结论数字必须来自引擎真实产物**
（`data/reports/`），页面页脚常驻「演示占位」标注，防止演示数字污染验收。

---

## 15 待拍板（UI 侧）

| 编号 | 事项 | 默认 |
|---|---|---|
| U-01 | 涨跌配色默认 | 中国市场红涨绿跌（可切国际） |
| U-02 | 表格密度默认 | 紧凑 32px |
| U-03 | 暗色模式期次 | P3 |
| U-04 | 移动端 | 只读查看，不做研究/交易操作 |
| U-05 | P1 阶段 UI 投入 | 先 CLI + HTML 报告，P2 再建控制台（对应 A-04） |
