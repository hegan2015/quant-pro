"""离线单文件 HTML 报告（FR-B-14）：内联 SVG，无 CDN、无外部字体，可离线打开。"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

DISCLAIMER = ("本报告为量化研究结论，不构成投资建议；系统不连接券商实盘通道。"
              "回测基于历史数据与既定成本假设，未来收益不确定。")


def _svg_line(series: list[tuple[str, str, bool, list[float]]], width=1000, height=260,
              pad=38, yfmt="{:0.3f}", labels: list[str] | None = None) -> str:
    vals = [v for _, _, _, s in series for v in s]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    lo -= span * 0.05
    hi += span * 0.05
    n = max(len(s) for _, _, _, s in series)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="净值曲线">']
    for k in range(5):
        yy = pad + k * (height - pad * 2) / 4
        v = hi - k * (hi - lo) / 4
        out.append(f'<line x1="{pad}" y1="{yy:.1f}" x2="{width - 12}" y2="{yy:.1f}" '
                   f'stroke="#E3E7ED" stroke-dasharray="3 3"/>')
        out.append(f'<text x="2" y="{yy + 3:.1f}" font-size="10" fill="#8A93A2">'
                   f'{yfmt.format(v)}</text>')
    for i in range(0, n, max(1, n // 8)):
        text = labels[i] if labels and i < len(labels) else f"D{i}"
        out.append(f'<text x="{pad + i * (width - pad - 12) / max(n - 1, 1) - 22:.1f}" '
                   f'y="{height - pad + 14}" font-size="10" fill="#8A93A2">{text}</text>')
    colors = ["#0F4C81", "#B26A00", "#2F8540", "#B33771", "#3B6FD4"]
    for j, (name, _c, dash, s) in enumerate(series):
        pts = " ".join(f"{pad + i * (width - pad - 12) / max(n - 1, 1):.1f},"
                       f"{height - pad - (v - lo) / (hi - lo) * (height - pad * 2):.1f}"
                       for i, v in enumerate(s))
        out.append(f'<polyline fill="none" stroke="{colors[j % 5]}" stroke-width="1.8" '
                   f'points="{pts}"{" stroke-dasharray=\"5 4\"" if dash else ""}/>')
    legend = "".join(f'<span style="color:{colors[j % 5]}">■ {name}</span>'
                     for j, (name, _, _, _) in enumerate(series))
    out.append("</svg>")
    return f'<div class="lg">{legend}</div>' + "".join(out)


def _svg_area(values: list[float], width=1000, height=110, color="#1F9254") -> str:
    lo, hi = min(values + [0.0]), max(values + [0.0])
    span = (hi - lo) or 1.0
    n = len(values)
    pts = " ".join(f"{38 + i * (width - 50) / max(n - 1, 1):.1f},"
                   f"{height - 24 - (v - lo) / span * (height - 40):.1f}"
                   for i, v in enumerate(values))
    base = height - 24 - (0 - lo) / span * (height - 40)
    return (f'<svg viewBox="0 0 {width} {height}"><polygon fill="{color}" opacity="0.16" '
            f'points="38,{base:.1f} {pts},{width - 12:.1f},{base:.1f}"/>'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{pts}"/>'
            f'<text x="2" y="12" font-size="10" fill="#8A93A2">0%</text>'
            f'<text x="2" y="{height - 10}" font-size="10" fill="#8A93A2">'
            f'{lo * 100:.1f}%</text></svg>')


def _heat(monthly: pd.DataFrame) -> str:
    cells = ["<table class='hm'><tr><th></th>"]
    cells += [f"<th>{m}月</th>" for m in monthly.columns]
    cells += ["<th>年度</th></tr>"]
    for y, row in monthly.iterrows():
        cells.append(f"<tr><th>{y}</th>")
        for v in row:
            cells.append(f"<td style='{_heat_style(v)}'>{v * 100:.1f}</td>")
        tot = float((1 + row).prod() - 1)
        cells.append(f"<td style='{_heat_style(tot)}'><b>{tot * 100:.1f}</b></td></tr>")
    cells.append("</table>")
    return "".join(cells)


def _heat_style(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "background:#EDEFF3"
    a = min(abs(v) / 0.10, 1.0) * 0.55 + 0.12
    if v > 0:
        return f"background:rgba(214,69,61,{a:.2f});color:#fff"
    return f"background:rgba(31,146,84,{a:.2f});color:#fff"


def _cards(m: dict) -> str:
    parts = []
    for grp, items in m.items():
        if not isinstance(items, dict):
            continue
        cells = "".join(
            f'<div class="k"><div class="kl">{k}</div><div class="kv">{_fmt(k, v)}</div></div>'
            for k, v in items.items())
        parts.append(f'<section class="card"><h2>{grp}</h2><div class="grid">{cells}</div></section>')
    return "".join(parts)


def _fmt(k: str, v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if any(x in k for x in ("收益", "波动", "回撤", "超额", "换手", "占比", "VaR", "alpha")):
            return f"{v * 100:.2f}%"
        return f"{v:.4f}"
    if isinstance(v, (int,)):
        return f"{v:,}"
    return str(v)


CSS = """
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;
 background:#F5F7FA;color:#1A1D22}
.wrap{max-width:1080px;margin:0 auto;padding:24px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 12px}
.sub{color:#545C68;font-size:13px}
.card{background:#fff;border:1px solid #E3E7ED;border-radius:8px;padding:16px;margin:16px 0;
 box-shadow:0 1px 2px rgba(16,24,40,.06)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.kl{font-size:12px;color:#545C68}.kv{font-size:18px;font-family:ui-monospace,monospace}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #E3E7ED;padding:6px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
table.hm td,table.hm th{padding:4px;text-align:center;font-size:11px;font-family:ui-monospace,monospace}
.lg{font-size:12px;color:#545C68;margin-bottom:6px}
.pass{color:#2F8540;font-weight:600}.FAIL{color:#B33771;font-weight:600}
.WARN{color:#B26A00;font-weight:600}.skipped{color:#8A93A2}
.foot{color:#8A93A2;font-size:12px;margin-top:24px;border-top:1px solid #E3E7ED;padding-top:12px}
.mono{font-family:ui-monospace,monospace;font-size:12px;color:#545C68}
"""


def write_report(res: dict, base_dir: Path, initial_capital: float) -> str:
    eq = res["equity"]
    nav = eq["nav"].astype(float).to_list()
    bench = eq["benchmark_nav"].astype(float).to_list()
    dd = (eq["nav"] / eq["nav"].cummax() - 1.0).to_list()
    monthly = res.get("monthly")
    if monthly is None:
        from core.performance.metrics import monthly_returns
        monthly = monthly_returns(eq)
    gate_rows = "".join(
        f"<tr><td>{c['lag']} {c['name']}</td><td class='{c['status']}'>{c['status']}</td>"
        f"<td style='text-align:left'>{c['detail']}</td></tr>"
        for c in res["lookahead"]["checks"])
    chk_rows = "".join(
        f"<tr><td>{r['项']}</td><td style='text-align:left'>{r['阈值']}</td>"
        f"<td>{_fmt(r['项'], r['本例'])}</td><td class='{r['判定']}'>{r['判定']}</td></tr>"
        for r in res["checklist"]["rows"])
    sens_rows = "".join(
        f"<tr><td>{k}</td><td>{_fmt('年化收益', v['年化收益'])}</td>"
        f"<td>{v['Sharpe']}</td><td>{_fmt('回撤', v['最大回撤'])}</td>"
        f"<td>{_fmt('占比', v.get('成本占毛收益'))}</td></tr>"
        for k, v in res["cost_sensitivity"].items()) or (
        "<tr><td colspan='5'>本次未跑敏感性（accept/backtest 加 --fast 或 sensitivity=False）"
        "</td></tr>")
    rej = res["rejected"]
    rej_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                       for k, v in sorted(rej.items(), key=lambda x: -x[1])) or \
        "<tr><td colspan='2'>无拒单</td></tr>"
    contrib = res["contributions"]
    c_rows = "".join(f"<tr><td>{s}</td><td>{v:,.0f}</td></tr>" for s, v in contrib.get("top", []))
    b_rows = "".join(f"<tr><td>{s}</td><td>{v:,.0f}</td></tr>" for s, v in contrib.get("bottom", []))

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>回测报告 {res['run_id']}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>quant-pro 回测报告 · {res['config']['strategy_id']} {res['config']['version']}</h1>
<div class="sub">{res['config']['start']} → {res['config']['end']} ·
 universe={res['config']['universe']} · 初始资金 {initial_capital:,.0f} 元 ·
 生成 {datetime.now():%Y-%m-%d %H:%M}</div>
<section class="card"><h2>可复现凭据</h2>
<div class="mono">run_id={res['run_id']}<br>config_hash={res['config_hash']}<br>
data_version={res['data_version']} · code_digest={res['code_digest']}<br>
cost={json.dumps(res['config']['cost'], ensure_ascii=False)}<br>
面板 {res['panels']['days']} 交易日 × {res['panels']['symbols']} 标的 ·
 {res['panels']['memory_mb']} MB · 耗时 {res['elapsed_sec']}s</div></section>
{_cards(res['metrics'])}
<section class="card"><h2>净值与基准</h2>
{_svg_line([("本组合", "#0F4C81", False, nav), ("基准 000300", "#B26A00", True, bench)],
            labels=[str(x)[:7] for x in eq.index])}
<h2>回撤</h2>{_svg_area(dd)}</section>
<section class="card"><h2>月度收益（行=年，列=月，单位 %）</h2>{_heat(monthly)}</section>
<section class="card"><h2>未来函数门禁（FR-B-13） ·
 总体 <span class="{res['lookahead']['lookahead_status']}">
 {res['lookahead']['lookahead_status']}</span></h2>
<table><tr><th>检查</th><th>状态</th><th style="text-align:left">说明</th></tr>{gate_rows}</table>
</section>
<section class="card"><h2>过拟合体检表 ·
 <span class="{res['checklist']['status']}">{res['checklist']['status']}</span></h2>
<table><tr><th>项</th><th style="text-align:left">阈值</th><th>本例</th><th>判定</th></tr>
{chk_rows}</table></section>
<section class="card"><h2>成本敏感性（FR-B-11）</h2>
<table><tr><th>滑点</th><th>年化</th><th>Sharpe</th><th>最大回撤</th><th>成本占比</th></tr>
{sens_rows}</table></section>
<section class="card"><h2>样本内 / 样本外</h2>
<table><tr><th>段</th><th>年化</th><th>Sharpe</th><th>最大回撤</th><th>换手笔数</th></tr>
<tr><td>IS {res['config']['start']}..{res['config']['train_end']}</td>
<td>{_fmt('年化收益', res['metrics_in_sample']['收益']['年化收益'])}</td>
<td>{res['metrics_in_sample']['比值']['Sharpe']}</td>
<td>{_fmt('回撤', res['metrics_in_sample']['风险']['max_drawdown'])}</td>
<td>{res['metrics_in_sample']['交易']['orders_filled']}</td></tr>
<tr><td>OOS {res['config']['train_end']}..{res['config']['end']}</td>
<td>{_fmt('年化收益', res['metrics_oos']['收益']['年化收益'])}</td>
<td>{res['metrics_oos']['比值']['Sharpe']}</td>
<td>{_fmt('回撤', res['metrics_oos']['风险']['max_drawdown'])}</td>
<td>{res['metrics_oos']['交易']['orders_filled']}</td></tr></table></section>
<section class="card"><h2>拒单分布（FR-B-05 留痕）</h2>
<table><tr><th>原因码</th><th>笔数</th></tr>{rej_rows}</table></section>
<section class="card"><h2>单票贡献 Top / Bottom（已实现毛额，元）</h2>
<div class="grid"><div><table><tr><th>标的</th><th>净额</th></tr>{c_rows}</table></div>
<div><table><tr><th>标的</th><th>净额</th></tr>{b_rows}</table></div></div></section>
<div class="foot">{DISCLAIMER}</div></div></body></html>"""

    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"backtest-{res['run_id']}-{date.today():%Y%m%d}.html"
    path.write_text(html, encoding="utf-8")
    (base_dir / f"backtest-{res['run_id']}-metrics.json").write_text(
        json.dumps({k: res[k] for k in ("run_id", "config", "config_hash", "data_version",
                                        "code_digest", "metrics", "metrics_in_sample",
                                        "metrics_oos", "cost_sensitivity", "checklist",
                                        "lookahead", "rejected", "trade_days", "panels",
                                        "elapsed_sec")},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not res["orders"].empty:
        res["orders"].to_csv(base_dir / f"backtest-{res['run_id']}-orders.csv",
                             index=False, encoding="utf-8-sig")
    return str(path)
