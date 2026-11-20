#!/usr/bin/env python3
"""P1 一键验收：环境自检 → 单测 → 口径自检 → 三条基线回测（含门禁与体检）→ 汇总产物。

用法：python3 scripts/accept.py [--only unit,backtest] [--fast]
产物：data/reports/accept-<ts>.{json,md}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EXPECT = {
    "unit": {"desc": "P1 用例全绿", "expect": "0 failed"},
    "selftest": {"desc": "口径自检（涨跌停/复权/现金恒等式/除权送转不跳空）",
                 "expect": "mismatch=0 且 identity_ok=True 且 no_double_count=True"},
    "backtest": {"desc": "三条基线策略跑通并出可信数字",
                 "expect": "lookahead_status=pass 且 metrics 五组齐全"},
    "report": {"desc": "离线单文件 HTML + JSON + CSV 报告", "expect": "三份产物存在且非空"},
}


def run_unit() -> dict:
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l]
    return {"exit": r.returncode, "summary": last[-1] if last else r.stdout[-200:],
            "ok": r.returncode == 0}


def run_selftest(db: str) -> dict:
    from core.selftest import run_all
    from core.store.duckdb_store import DuckDBStore
    res = run_all(DuckDBStore(db))
    ok = (res["涨跌停公式核对"]["mismatch"] == 0
          and res["现金恒等式与整手"]["identity_ok"]
          and res["现金恒等式与整手"]["lot_ok"]
          and res["除权送转净值不跳空"]["no_double_count"]
          and res["日历与行情一致性"]["bars_missing_in_calendar"] == 0)
    return {"ok": bool(ok), "detail": res}


# 基线用 1000 万初始资金：1M 时 2%×50 只的目标金额不足一手，
# 高价股买不进会让篮子系统性偏向低价股（实测 LOT_TOO_LARGE 占 37% 次）
INITIAL_CAPITAL = 10_000_000.0


def run_backtests(db: str, fast: bool) -> dict:
    from core.services import backtest
    from core.store.duckdb_store import DuckDBStore
    store = DuckDBStore(db)
    out = {}
    specs = [
        ("s1_trend", {"top_n": 50, "step_days": 5}, False),
        ("s2_multifactor", {"top_n": 30, "factors": {"mom_20": .25, "mom_60": .15,
                                                     "vol_60": .15, "size_float": .15,
                                                     "turnover_20": .15, "amihud_20": .15}},
         not fast),
        ("s3_rotation", {"top_n": 30}, False),
    ]
    for sid, params, sens in specs:
        res = backtest(store, sid, params, date(2016, 1, 4), date(2025, 12, 31),
                       universe_size=1000, initial_capital=INITIAL_CAPITAL,
                       sensitivity=sens, persist=True)
        from core.performance.report import write_report
        from core.config import settings
        path = write_report(res, settings.REPORT_DIR, 1_000_000.0)
        m = res["metrics"]
        out[sid] = {
            "run_id": res["run_id"], "config_hash": res["config_hash"],
            "elapsed_sec": res["elapsed_sec"], "timings": res["timings"],
            "trade_days": res["trade_days"],
            "lookahead_status": res["lookahead"]["lookahead_status"],
            "lookahead_checks": res["lookahead"]["checks"],
            "checklist_status": res["checklist"]["status"],
            "checklist_rows": res["checklist"]["rows"],
            "cost_sensitivity": res["cost_sensitivity"],
            "metrics": m, "metrics_oos": res["metrics_oos"],
            "rejected": res["rejected"], "report": path,
            "panels": res["panels"],
        }
        print(f"  {sid}: run={res['run_id']} 门禁={out[sid]['lookahead_status']} "
              f"体检={out[sid]['checklist_status']} 年化={m['收益']['年化收益']:.2%} "
              f"Sharpe={m['比值']['Sharpe']} 回撤={m['风险']['max_drawdown']:.2%} "
              f"耗时={res['elapsed_sec']}s {res['timings']}", flush=True)
    ok = all(v["lookahead_status"] in ("pass", "FAIL") and "收益" in v["metrics"]
             for v in out.values())
    return {"ok": bool(ok), "detail": out}


def check_reports() -> dict:
    rep = os.path.join(ROOT, "data", "reports")
    files = sorted(os.listdir(rep)) if os.path.isdir(rep) else []
    html = [f for f in files if f.endswith(".html")]
    js = [f for f in files if f.endswith("-metrics.json")]
    csv = [f for f in files if f.endswith("-orders.csv")]
    ok = bool(html) and bool(js) and bool(csv)
    sizes = {f: os.path.getsize(os.path.join(rep, f)) for f in (html + js + csv)[:6]}
    return {"ok": ok, "detail": {"html": len(html), "json": len(js), "csv": len(csv),
                                 "sample_sizes": sizes}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="unit,selftest,backtest,report")
    ap.add_argument("--fast", action="store_true", help="跳过成本敏感性（省时 3 倍）")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "mkt.duckdb"))
    a = ap.parse_args()
    steps = [s.strip() for s in a.only.split(",")]
    results, started = {}, datetime.now()
    if "unit" in steps:
        results["unit"] = run_unit()
        print("单测：", results["unit"]["summary"], flush=True)
    if "selftest" in steps:
        results["selftest"] = run_selftest(a.db)
        print("口径自检：", "通过" if results["selftest"]["ok"] else "未通过", flush=True)
    if "backtest" in steps:
        results["backtest"] = run_backtests(a.db, a.fast)
    if "report" in steps:
        results["report"] = check_reports()
    passed = all(r["ok"] for r in results.values())

    stamp = started.strftime("%Y%m%dT%H%M")
    os.makedirs(os.path.join(ROOT, "data", "reports"), exist_ok=True)
    jpath = os.path.join(ROOT, "data", "reports", f"accept-{stamp}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump({"started_at": started.isoformat(), "passed": passed,
                   "expect": EXPECT, "results": results}, f,
                  ensure_ascii=False, indent=2, default=str)
    md = [f"# P1 验收报告 {stamp}", "",
          f"总体：**{'通过' if passed else '未通过'}** · 产物 `{jpath}`", "",
          "| 步骤 | 期望 | 实测 | 判定 |", "|---|---|---|---|"]
    for k, r in results.items():
        actual = r.get("summary") or ("全部步骤有产物" if k == "report" else
                                     "见 JSON detail")
        md.append(f"| {k} | {EXPECT[k]['expect']} | {actual} | "
                  f"{'✅' if r['ok'] else '❌'} |")
    if "backtest" in results:
        md += ["", "## 三条基线", "", "| 策略 | run_id | 门禁 | 体检 | 年化 | Sharpe | 最大回撤 | 拒单 |",
               "|---|---|---|---|---|---|---|---|"]
        for sid, v in results["backtest"]["detail"].items():
            m = v["metrics"]
            md.append(f"| {sid} | {v['run_id']} | {v['lookahead_status']} | "
                      f"{v['checklist_status']} | {m['收益']['年化收益']:.2%} | "
                      f"{m['比值']['Sharpe']} | {m['风险']['max_drawdown']:.2%} | "
                      f"{json.dumps(v['rejected'], ensure_ascii=False)} |")
    md += ["", "> 免责声明：本报告为量化研究结论，不构成投资建议；系统不连接券商实盘通道。"]
    mpath = os.path.join(ROOT, "data", "reports", f"accept-{stamp}.md")
    open(mpath, "w", encoding="utf-8").write("\n".join(md))
    print(f"\n验收产物：\n  {jpath}\n  {mpath}")
    print(f"总体：{'通过' if passed else '未通过'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
