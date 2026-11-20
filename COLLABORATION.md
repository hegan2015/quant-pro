# quant-pro 协作指南（与同工作区其他系统并行开发时必读）

## 1 资源边界

| 项 | 约定 | 原因 |
|---|---|---|
| 目录 | 只在 `quant-pro/` 内改动 | 并行会话同改工作区，跨目录改动易互相覆盖 |
| 端口 | 控制台 8101 / API 8102 / worker metrics 8103 / TimescaleDB 5433 | 8080–8099、8100 已被 payment/ride/yiwu/cs/claim/ops 占满 |
| 数据库 | **不复用** 3306 MySQL、6379 Redis、9876 RocketMQ、7233 Temporal、9000 MinIO | 他人重启中间件会导致本系统连接与计数漂移 |
| 行情库 | `data/mkt.duckdb`（进程内，无端口） | 无容器也能跑；文件被独占，勿并发双写 |
| 密钥 | `~/.config/quant-pro/settings.json`（600），仓库只留 `config/settings.example.json` | 口令不进仓库、不进 argv |

## 2 数据保护

- `data/mkt.duckdb`、`data/reports/` 删除或重建前必须用户确认。
- 行情表 `daily_bar` 只 upsert 与追加；修正走 `data_amendment` 留痕，禁止 UPDATE 覆盖原行。
- `data_issue` 是派生诊断表，质量作业按窗口重生成（`clear_auto_issues`），不视为账本数据。
- 模拟盘账本（P2）落地后：ledger 只追加，重放生成独立副本，不改原账本。

## 3 提交纪律

- 全绿才提交：`bash scripts/verify.sh` 退出码 0（单测 + 口径自检 + 三条基线回测 + 门禁）。
- 文档套须齐：README / REQUIREMENTS / ARCHITECTURE / DETAILED-DESIGN / UI-DESIGN / TEST-ACCEPTANCE。
- 只 stage 自己的文件；并行会话可能同时改同一仓库，提交前 `git status` 复核。
- 推送由用户执行（SSH 可用，无 gh/PAT）。

## 4 与其他系统的接口面

当前无跨系统调用。若将来与 payment-pro 联动（例如资金账户对账），走 HTTP 且必须带登录态：
payment 控制台是 Bearer 鉴权，匿名访问会被门禁拒。
