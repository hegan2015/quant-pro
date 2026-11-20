#!/usr/bin/env python3
"""生成 quant-pro 高保真可点击视觉稿（离线 HTML，无 CDN、无外部字体）。

用法：python3 prototype/build.py            # 生成 prototype/pages/*.html
      python3 prototype/build.py --check    # 只校验，不写文件

纪律：页面中的全部数字均为「演示占位」，非真实回测输出，页脚常驻标注（UI-DESIGN §14）。
"""
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "pages")
ASSETS = os.path.join(HERE, "assets")

TOKENS_CSS = """
:root{
  --brand-600:#0F4C81; --brand-100:#E8F0FE;
  --market-up:#D6453D; --market-down:#1F9254; --market-flat:#8A93A2;
  --ok-600:#2F8540; --warn-600:#B26A00; --err-600:#B33771; --info-600:#3B6FD4;
  --text-1:#1A1D22; --text-2:#545C68; --text-3:#8A93A2;
  --bg-0:#FFFFFF; --bg-1:#F5F7FA; --bg-2:#EDEFF3;
  --line-1:#E3E7ED; --line-2:#CDD4DE;
  --chart-1:#0F4C81; --chart-2:#B26A00; --chart-3:#2F8540; --chart-4:#B33771;
  --chart-5:#3B6FD4; --chart-6:#7A5AF8; --chart-7:#0FA3A3; --chart-8:#6B7280;
  --font-ui:-apple-system,"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif;
  --font-num:"JetBrains Mono","SF Mono",ui-monospace,monospace;
  --fs-xs:12px; --fs-sm:13px; --fs-base:14px; --fs-lg:16px; --fs-xl:20px; --fs-2xl:24px;
  --lh-tight:1.25; --lh-normal:1.5;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px; --sp-7:48px;
  --r-sm:4px; --r-md:8px;
  --sh-1:0 1px 2px rgba(16,24,40,.06); --sh-2:0 4px 16px rgba(16,24,40,.10);
  --row-h-compact:32px; --row-h-default:40px;
  --z-nav:100; --z-dropdown:500; --z-modal:900; --z-toast:1000;
}
[data-theme="dark"]{
  --bg-0:#12161C; --bg-1:#171D25; --bg-2:#1E252F;
  --text-1:#E6EAF0; --text-2:#AEB8C6; --text-3:#7C8797;
  --line-1:#262F3A; --line-2:#37424F; --sh-2:0 4px 16px rgba(0,0,0,.5);
}
"""

APP_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:var(--font-ui);font-size:var(--fs-base);color:var(--text-1);
  background:var(--bg-1);line-height:var(--lh-normal)}
a{color:var(--brand-600);text-decoration:none}
.num{font-family:var(--font-num);font-variant-numeric:tabular-nums}
.up{color:var(--market-up)} .down{color:var(--market-down)} .flat{color:var(--market-flat)}
.top{position:sticky;top:0;z-index:var(--z-nav);background:var(--bg-0);border-bottom:1px solid var(--line-1);
  display:flex;align-items:center;gap:var(--sp-4);height:52px;padding:0 var(--sp-5)}
.logo{font-weight:700;color:var(--brand-600);letter-spacing:.5px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-xs);
  padding:2px 8px;border-radius:999px;border:1px solid var(--line-2);color:var(--text-2);background:var(--bg-0)}
.chip-env-prod{border-color:var(--err-600);color:var(--err-600);font-weight:700}
.chip-warn{border-color:var(--warn-600);color:var(--warn-600)}
.top-spacer{flex:1}
.search{width:230px;height:30px;border:1px solid var(--line-2);border-radius:var(--r-sm);
  padding:0 var(--sp-3);font-size:var(--fs-sm);color:var(--text-3);background:var(--bg-1)}
.shell{display:flex;min-height:calc(100vh - 52px)}
.nav{width:212px;flex:0 0 212px;background:var(--bg-0);border-right:1px solid var(--line-1);
  padding:var(--sp-4) 0}
.nav-group{margin-bottom:var(--sp-3)}
.nav-title{font-size:var(--fs-xs);color:var(--text-3);padding:0 var(--sp-4) var(--sp-1);
  text-transform:none;letter-spacing:.04em}
.nav-item{display:flex;align-items:center;gap:8px;padding:6px var(--sp-4);font-size:var(--fs-sm);
  color:var(--text-2);border-left:2px solid transparent}
.nav-item:hover{background:var(--bg-1);color:var(--text-1)}
.nav-item.active{background:var(--brand-100);color:var(--brand-600);border-left-color:var(--brand-600);font-weight:600}
.badge{margin-left:auto;min-width:18px;text-align:center;font-size:11px;padding:0 5px;border-radius:999px;
  font-family:var(--font-num);background:var(--bg-2);color:var(--text-2)}
.badge-err{background:#FBE7F1;color:var(--err-600)} .badge-warn{background:#FDF1E3;color:var(--warn-600)}
.main{flex:1;min-width:0;padding:var(--sp-5)}
.crumb{font-size:var(--fs-xs);color:var(--text-3);margin-bottom:var(--sp-2)}
.pagehead{display:flex;align-items:flex-end;gap:var(--sp-4);margin-bottom:var(--sp-5)}
.pagehead h1{margin:0;font-size:var(--fs-2xl);line-height:var(--lh-tight)}
.pagehead p{margin:4px 0 0;font-size:var(--fs-sm);color:var(--text-2)}
.head-actions{margin-left:auto;display:flex;gap:var(--sp-2)}
.btn{height:32px;padding:0 var(--sp-4);white-space:nowrap;border-radius:var(--r-sm);border:1px solid var(--line-2);
  background:var(--bg-0);color:var(--text-1);font-size:var(--fs-sm);cursor:pointer;font-family:var(--font-ui)}
.btn:hover{border-color:var(--brand-600);color:var(--brand-600)}
.btn-primary{background:var(--brand-600);border-color:var(--brand-600);color:#fff}
.btn-primary:hover{background:#0d4271;color:#fff}
.btn-danger{background:var(--err-600);border-color:var(--err-600);color:#fff}
.btn-sm{height:26px;padding:0 var(--sp-3);font-size:var(--fs-xs)}
.btn[disabled]{opacity:.45;cursor:not-allowed}
.btn[disabled]:hover{border-color:var(--line-2);color:var(--text-1)}
.grid{display:grid;gap:var(--sp-4)}
.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
.g3{grid-template-columns:repeat(3,minmax(0,1fr))}
.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.g-2-1{grid-template-columns:minmax(0,2fr) minmax(0,1fr)}
.card{background:var(--bg-0);border:1px solid var(--line-1);border-radius:var(--r-md);
  box-shadow:var(--sh-1);padding:var(--sp-4)}
.card-h{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-3)}
.card-h h2{margin:0;font-size:var(--fs-base);font-weight:600}
.card-h .sub{font-size:var(--fs-xs);color:var(--text-3)}
.card-h .right{margin-left:auto;display:flex;gap:6px;align-items:center}
.kpi .label{font-size:var(--fs-xs);color:var(--text-2)}
.kpi .value{font-size:var(--fs-xl);margin-top:2px}
.kpi .delta{font-size:var(--fs-xs);margin-top:2px}
.tag{display:inline-flex;align-items:center;gap:4px;font-size:var(--fs-xs);padding:1px 8px;
  border-radius:999px;border:1px solid var(--line-2);color:var(--text-2);background:var(--bg-0);white-space:nowrap}
.tag-ok{border-color:var(--ok-600);color:var(--ok-600);background:#EAF4EC}
.tag-warn{border-color:var(--warn-600);color:var(--warn-600);background:#FDF3E6}
.tag-err{border-color:var(--err-600);color:var(--err-600);background:#FBEAF2}
.tag-info{border-color:var(--info-600);color:var(--info-600);background:#EAF1FD}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot-ok{background:var(--ok-600)} .dot-warn{background:var(--warn-600)}
.dot-err{background:var(--err-600)} .dot-idle{background:var(--market-flat)}
table{width:100%;border-collapse:collapse;font-size:var(--fs-sm)}
th{text-align:left;font-weight:600;color:var(--text-2);font-size:var(--fs-xs);
  border-bottom:1px solid var(--line-2);padding:7px var(--sp-2);white-space:nowrap;background:var(--bg-0)}
td{height:var(--row-h-compact);padding:0 var(--sp-2);border-bottom:1px solid var(--line-1);
  color:var(--text-1);white-space:nowrap;vertical-align:middle}
tr:hover td{background:var(--bg-1)}
td.r,th.r{text-align:right}
td.dim{color:var(--text-2)}
.bar-track{height:6px;border-radius:3px;background:var(--bg-2);overflow:hidden;min-width:70px}
.bar-fill{height:100%;background:var(--brand-600)}
.banner{display:flex;align-items:center;gap:var(--sp-3);padding:10px var(--sp-4);border-radius:var(--r-md);
  border:1px solid var(--line-1);background:var(--bg-0);font-size:var(--fs-sm);margin-bottom:var(--sp-4)}
.banner-err{border-color:var(--err-600);background:#FDF0F6;color:#7d2450}
.banner-warn{border-color:var(--warn-600);background:#FEF6EA;color:#7a4a05}
.filters{display:flex;flex-wrap:wrap;gap:var(--sp-2);align-items:center;margin-bottom:var(--sp-4)}
.field{display:flex;flex-direction:column;gap:4px}
.field label{font-size:var(--fs-xs);color:var(--text-2)}
.input,select{height:30px;border:1px solid var(--line-2);border-radius:var(--r-sm);padding:0 var(--sp-2);
  font-size:var(--fs-sm);background:var(--bg-0);color:var(--text-1);min-width:120px}
.seg{display:inline-flex;border:1px solid var(--line-2);border-radius:var(--r-sm);overflow:hidden}
.seg span{padding:4px 10px;font-size:var(--fs-xs);color:var(--text-2);background:var(--bg-0)}
.seg span.on{background:var(--brand-600);color:#fff}
.legend{display:flex;gap:var(--sp-3);align-items:center;font-size:var(--fs-xs);color:var(--text-2)}
.legend i{display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:5px}
.heat{display:grid;grid-template-columns:52px repeat(12,minmax(0,1fr)) 58px;gap:2px;font-size:11px}
.neg{color:var(--err-600)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--sp-3);margin-top:12px}
.stat .label{font-size:var(--fs-xs);color:var(--text-2)}
.stat .v{font-size:var(--fs-base);margin-top:2px}
.heat .h{color:var(--text-3);text-align:right;padding:4px 6px;font-size:11px}
.heat .c{text-align:center;padding:5px 2px;border-radius:3px;font-family:var(--font-num);font-size:11px}
.matrix{display:grid;gap:2px;font-size:11px;font-family:var(--font-num)}
.mx{padding:5px 2px;text-align:center;border-radius:3px}
.mx-h{color:var(--text-3);text-align:center;padding:4px 2px}
.mx.diag{background:var(--bg-2);color:var(--text-3)}
.mx.hot{outline:2px solid var(--err-600);font-weight:700;color:var(--err-600)}
.rows{display:flex;flex-direction:column;gap:var(--sp-2)}
.row{display:flex;align-items:center;gap:var(--sp-2);font-size:var(--fs-sm)}
.row .k{color:var(--text-2);min-width:150px}
.progress{height:8px;background:var(--bg-2);border-radius:4px;overflow:hidden;flex:1}
.progress i{display:block;height:100%;background:var(--brand-600)}
.mono-sm{font-size:var(--fs-xs);font-family:var(--font-num);color:var(--text-2)}
.checks{display:grid;gap:6px}
.check{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);padding:6px var(--sp-3);
  border:1px solid var(--line-1);border-radius:var(--r-sm);background:var(--bg-0)}
.check .n{min-width:150px}
.check.pass{border-left:3px solid var(--ok-600)}
.check.fail{border-left:3px solid var(--err-600);background:#FDF0F6}
.check.warn{border-left:3px solid var(--warn-600);background:#FEF6EA}
.state{border:1px dashed var(--line-2);border-radius:var(--r-md);padding:var(--sp-4);
  text-align:center;color:var(--text-2);font-size:var(--fs-sm);background:var(--bg-0)}
.state h3{margin:0 0 6px;font-size:var(--fs-base);color:var(--text-1)}
.state.err{border-color:var(--err-600);border-style:solid}
.sk{border-radius:var(--r-sm);background:linear-gradient(90deg,var(--bg-2) 25%,var(--bg-1) 50%,var(--bg-2) 75%);
  background-size:200% 100%;animation:sk 1.2s infinite}
@keyframes sk{0%{background-position:200% 0}100%{background-position:-200% 0}}
.skel-row{height:22px;margin-bottom:8px}
.footer{padding:var(--sp-4) var(--sp-5) var(--sp-6);color:var(--text-3);font-size:var(--fs-xs);
  border-top:1px solid var(--line-1);margin-top:var(--sp-5);background:var(--bg-0)}
.footer b{color:var(--text-2)}
.pb{display:flex;gap:6px;align-items:center;justify-content:flex-end;margin-top:var(--sp-3);
  font-size:var(--fs-xs);color:var(--text-2)}
.hint{font-size:var(--fs-xs);color:var(--text-3);margin-top:6px}
.qmark{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;
  border:1px solid var(--line-2);color:var(--text-3);font-size:10px;margin-left:4px;cursor:help}
.tabs{display:flex;gap:var(--sp-4);border-bottom:1px solid var(--line-1);margin-bottom:var(--sp-4)}
.tabs span{padding:6px 0;font-size:var(--fs-sm);color:var(--text-2);border-bottom:2px solid transparent}
.tabs span.on{color:var(--brand-600);border-bottom-color:var(--brand-600);font-weight:600}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{font-family:var(--font-num);font-size:10px;fill:var(--text-3)}
svg .ax{stroke:var(--line-1);stroke-width:1}
@media (max-width:1024px){.g4{grid-template-columns:repeat(2,minmax(0,1fr))}.g-2-1{grid-template-columns:1fr}
 .search{width:140px}}
@media (max-width:768px){.nav{display:none}.g3,.g2{grid-template-columns:1fr}}
"""

NAV = [
    ("概览", [("dashboard.html", "总览驾驶舱", None, None)]),
    ("数据", [
        ("data-quality.html", "数据质量", 7, "err"),
        ("data-amendments.html", "修正留痕", None, None),
        ("data-sources.html", "双源比对", None, None),
        ("data-jobs.html", "作业与水位", 2, "warn"),
    ]),
    ("研究", [
        ("research-factors.html", "因子库", None, None),
        ("research-strategies.html", "策略与版本", None, None),
        ("research-ai-lab.html", "AI 研究台", None, None),
    ]),
    ("回测", [
        ("backtest.html", "发起与运行详情", None, None),
        ("backtest-runs.html", "回测记录", None, None),
    ]),
    ("信号", [
        ("signals.html", "当日信号与发布", None, None),
        ("signals-history.html", "历史信号", None, None),
    ]),
    ("模拟盘", [
        ("paper.html", "持仓与订单", None, None),
        ("paper-recon.html", "对账与追溯", 1, "err"),
        ("paper-replay.html", "账本重放", None, None),
    ]),
    ("风控", [
        ("risk.html", "规则与事件", 3, "err"),
        ("risk-breaker.html", "熔断状态", None, None),
    ]),
    ("系统", [
        ("system-config.html", "参数与口径", None, None),
        ("system-audit.html", "审计日志", None, None),
    ]),
]

DISCLAIMER = (
    "<b>免责声明</b>：本系统输出为量化研究结论，不构成投资建议，不连接券商实盘通道。"
    " &nbsp;|&nbsp; <b>视觉稿标注</b>：本页所有数字为演示占位，非真实回测输出；"
    "运行态数字必须来自引擎产物（见 UI-DESIGN §14 评审纪律）。"
    " &nbsp;|&nbsp; store=TimescaleDB:5433 &nbsp; data_version=a7f3c1 &nbsp; 时区 Asia/Shanghai &nbsp; 角色=researcher"
)


def nav_html(active):
    out = ['<nav class="nav" aria-label="主导航">']
    for group, items in NAV:
        out.append('<div class="nav-group"><div class="nav-title">%s</div>' % group)
        for href, label, badge, tone in items:
            cls = "nav-item active" if href == active else "nav-item"
            cur = ' aria-current="page"' if href == active else ""
            b = ""
            if badge is not None:
                b = '<span class="badge badge-%s">%d</span>' % (tone or "idle", badge)
            out.append('<a class="%s" href="%s"%s>%s%s</a>' % (cls, href, cur, label, b))
        out.append("</div>")
    out.append("</nav>")
    return "".join(out)


def topbar(extra=""):
    return (
        '<header class="top">'
        '<span class="logo">QUANT·PRO</span>'
        '<span class="chip chip-env-prod">PROD</span>'
        '<span class="chip">最新交易日 2026-11-20</span>'
        '<span class="chip chip-warn">缺口 1 日</span>'
        '<span class="chip">Timescale</span>'
        '<span class="top-spacer"></span>'
        + extra +
        '<input class="search" placeholder="搜索 标的 / 策略 / run_id" aria-label="搜索">'
        '<span class="chip">通知 <span class="badge badge-err">4</span></span>'
        '<span class="chip">张研究员 · researcher</span>'
        "</header>"
    )


def page(fname, title, sub, body, actions="", crumb="", tabs=""):
    tab_html = ""
    if tabs:
        tab_html = '<div class="tabs">' + "".join(
            '<span class="%s">%s</span>' % ("on" if i == 0 else "", t) for i, t in enumerate(tabs)
        ) + "</div>"
    html = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · quant-pro 视觉稿</title>
<link rel="stylesheet" href="../assets/tokens.css"><link rel="stylesheet" href="../assets/app.css">
</head><body>
%s
<div class="shell">
%s
<main class="main">
<div class="crumb">%s</div>
<div class="pagehead"><div><h1>%s</h1><p>%s</p></div><div class="head-actions">%s</div></div>
%s
%s
</main>
</div>
<footer class="footer">%s</footer>
</body></html>""" % (
        title, topbar(), nav_html(fname), crumb or ("量化研究 / %s" % title),
        title, sub, actions, tab_html, body, DISCLAIMER,
    )
    return fname, html


def tag(text, tone=""):
    return '<span class="tag tag-%s">%s</span>' % (tone, text) if tone else '<span class="tag">%s</span>' % text


def delta(v, suffix="%", digits=2):
    cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "—")
    return '<span class="num %s">%+.*f%s%s</span>' % (cls, digits, v, suffix, arrow)


def kpi(label, value, dl=None, note=""):
    d = ('<div class="delta">%s</div>' % dl) if dl else ""
    q = '<span class="qmark" title="%s">?</span>' % note if note else ""
    return ('<div class="card kpi"><div class="label">%s%s</div><div class="value num">%s</div>%s</div>'
            % (label, q, value, d))


def series_walk(n, start, vol, drift, seed):
    rnd = random.Random(seed)
    out, v = [], start
    for _ in range(n):
        v *= 1 + drift / 252 + rnd.gauss(0, vol / math.sqrt(252))
        out.append(v)
    return out


def xlabels(n):
    days, y, m = [], 2022, 1
    for i in range(n):
        if i % 22 == 0:
            days.append("%d-%02d" % (y, m))
            m += 1
            if m > 12:
                m, y = 1, y + 1
        else:
            days.append("")
    return days


def line_chart(series, width=1040, height=250, pad=34, bands=None, yfmt="%0.2f"):
    """series: [(name, color, dash, [values])]. bands: [(lo,hi,fill)] 背景带。"""
    all_v = [v for _, _, _, vals in series for v in vals]
    if bands:
        for lo, hi, _ in bands:
            all_v += [lo, hi]
    lo, hi = min(all_v), max(all_v)
    span = (hi - lo) or 1.0
    lo -= span * 0.06
    hi += span * 0.06
    span = hi - lo
    n = max(len(v) for _, _, _, v in series)

    def px(i):
        return pad + i * (width - pad - 14) / max(n - 1, 1)

    def py(v):
        return height - pad - (v - lo) / span * (height - pad * 2)

    p = ['<svg viewBox="0 0 %d %d" role="img" aria-label="净值曲线，含数据表格替代链接">' % (width, height)]
    for k in range(5):
        yy = pad + k * (height - pad * 2) / 4
        val = hi - k * span / 4
        p.append('<line class="ax" x1="%d" y1="%0.1f" x2="%d" y2="%0.1f" %s/>'
                 % (pad, yy, width - 14, yy, 'stroke-dasharray="3 3"' if k else ""))
        p.append('<text x="0" y="%0.1f">%s</text>' % (yy + 3, yfmt % val))
    for lo_b, hi_b, fill in (bands or []):
        p.append('<rect x="%d" y="%0.1f" width="%0.1f" height="%0.1f" fill="%s" opacity="0.10"/>'
                 % (pad, py(hi_b), width - pad - 14, py(lo_b) - py(hi_b), fill))
    if lo < 0 < hi:
        p.append('<line x1="%d" y1="%0.1f" x2="%d" y2="%0.1f" stroke="var(--line-2)" stroke-width="1"/>'
                 % (pad, py(0), width - 14, py(0)))
    for name, color, dash, vals in series:
        pts = " ".join("%0.1f,%0.1f" % (px(i), py(v)) for i, v in enumerate(vals))
        p.append('<polyline fill="none" stroke="%s" stroke-width="1.8" points="%s"%s/>'
                 % (color, pts, ' stroke-dasharray="5 4"' if dash else ""))
    labs = xlabels(n)
    for i in range(0, n, 60):
        if labs[i]:
            p.append('<text x="%0.1f" y="%d">%s</text>' % (px(i) - 14, height - pad + 16, labs[i]))
    p.append("</svg>")
    return "".join(p)


def area_line(values, width=1040, height=90, pad=22, color="var(--market-down)"):
    lo, hi = min(values + [0]), max(values + [0])
    span = (hi - lo) or 1.0
    n = len(values)

    def px(i):
        return pad + i * (width - pad - 14) / max(n - 1, 1)

    def py(v):
        return height - pad - (v - lo) / span * (height - pad * 2)

    pts = " ".join("%0.1f,%0.1f" % (px(i), py(v)) for i, v in enumerate(values))
    mn = min(values)
    return ('<svg viewBox="0 0 %d %d"><polygon fill="%s" opacity="0.16" points="%0.1f,%0.1f %s %0.1f,%0.1f"/>'
            '<polyline fill="none" stroke="%s" stroke-width="1.4" points="%s"/>'
            '<line class="ax" x1="%d" y1="%0.1f" x2="%d" y2="%0.1f"/>'
            '<text x="0" y="%0.1f">0.0%%</text>'
            '<text x="0" y="%0.1f">%0.1f%%</text>'
            '<line class="ax" x1="%d" y1="%0.1f" x2="%d" y2="%0.1f" stroke-dasharray="3 3"/></svg>'
            % (width, height, color, px(0), py(0), pts, px(n - 1), py(0), color, pts,
               pad, py(0), width - 14, py(0), pad, py(mn) + 3, mn,
               pad, py(mn), width - 14, py(mn)))


def bars(vals, labels, width=520, height=150, color="var(--chart-1)"):
    lo, hi = min(vals + [0]), max(vals + [0])
    span = (hi - lo) or 1.0
    n = len(vals)
    bw = (width - 40) / n * 0.62
    p = ['<svg viewBox="0 0 %d %d">' % (width, height)]
    zero = height - 24 - (0 - lo) / span * (height - 40)
    p.append('<line class="ax" x1="34" y1="%0.1f" x2="%d" y2="%0.1f"/>' % (zero, width, zero))
    for i, v in enumerate(vals):
        x = 40 + i * (width - 40) / n
        y = height - 24 - (v - lo) / span * (height - 40)
        c = "var(--market-up)" if v > 0 else "var(--market-down)"
        top, h = (min(y, zero), abs(zero - y)) if v > 0 else (zero, abs(y - zero))
        p.append('<rect x="%0.1f" y="%0.1f" width="%0.1f" height="%0.1f" fill="%s" rx="2"/>'
                 % (x, top, bw, h, c if color is None else color))
        p.append('<text x="%0.1f" y="%d">%s</text>' % (x, height - 8, labels[i]))
        p.append('<text x="%0.1f" y="%0.1f">%0.1f</text>' % (x - 4, min(top, y) - 4, v))
    p.append("</svg>")
    return "".join(p)


def month_heat(years):
    rnd = random.Random(11)
    months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
    cells = ['<div class="heat"><div class="h"></div>' + "".join('<div class="h">%s</div>' % m for m in months)
             + '<div class="h">年度</div>']
    for yi, year in enumerate(years):
        row = [rnd.uniform(-0.09, 0.12) for _ in range(12)]
        total = 1.0
        for v in row:
            total *= 1 + v
        cells.append('<div class="h">%d</div>' % year)
        for v in row:
            cells.append('<div class="c" style="%s">%s</div>' % (heat_style(v), "%0.1f%%" % (v * 100)))
        cells.append('<div class="c" style="%s">%s</div>' % (heat_style(total - 1), "%0.1f%%" % ((total - 1) * 100)))
    cells.append("</div>")
    return "".join(cells)


def heat_style(v):
    if abs(v) < 0.0005:
        return "background:var(--bg-2);color:var(--text-3)"
    alpha = min(abs(v) / 0.10, 1.0) * 0.55 + 0.10
    if v > 0:
        return "background:rgba(214,69,61,%0.2f);color:#fff" % alpha
    return "background:rgba(31,146,84,%0.2f);color:#fff" % alpha


def corr_matrix(names, seed=3):
    rnd = random.Random(seed)
    n = len(names)
    style = "grid-template-columns:repeat(%d,minmax(0,1fr))" % (n + 1)
    out = ['<div class="matrix" style="%s">' % style, '<div class="mx-h"></div>']
    out += ['<div class="mx-h">%s</div>' % s[:6] for s in names]
    for i, a in enumerate(names):
        out.append('<div class="h mx-h">%s</div>' % a[:7])
        for j, b in enumerate(names):
            if j < i:
                out.append('<div class="mx"></div>')
                continue
            if i == j:
                out.append('<div class="mx diag">1.00</div>')
                continue
            r = rnd.uniform(-0.5, 0.99)
            hot = " hot" if r > 0.95 else ""
            bg = "rgba(15,76,129,%0.2f)" % abs(r) if r > 0 else "rgba(178,106,0,%0.2f)" % abs(r)
            out.append('<div class="mx%s" style="background:%s;color:#fff">%0.2f</div>' % (hot, bg, r))
    out.append("</div>")
    return "".join(out)


def card(title, body, sub="", right=""):
    return ('<section class="card"><div class="card-h"><h2>' + title + '</h2>'
            + ('<span class="sub">' + sub + "</span>" if sub else "")
            + '<div class="right">' + right + "</div></div>" + body + "</section>")


def table(headers, rows, aligns=None, pager_total=None, note_text=""):
    aligns = aligns or ["l"] * len(headers)
    th = "".join('<th class="%s">%s</th>' % ("r" if a == "r" else "l", h) for h, a in zip(headers, aligns))
    tr = []
    for row in rows:
        tds = "".join('<td class="%s">%s</td>' % ("" if aligns[i] == "l" else "r", cell)
                      for i, cell in enumerate(row))
        tr.append("<tr>" + tds + "</tr>")
    pg = ""
    if pager_total:
        pg = ('<div class="pb"><span>共 ' + str(pager_total) + ' 条 · 服务端分页</span>'
              '<button class="btn btn-sm">上一页</button><button class="btn btn-sm" aria-current="page">1</button>'
              '<button class="btn btn-sm">2</button><button class="btn btn-sm">下一页</button>'
              '<span>每页 50</span></div>')
    nt = ('<div class="hint">' + note_text + "</div>") if note_text else ""
    return ('<div style="overflow-x:auto"><table><thead><tr>' + th + "</tr></thead><tbody>"
            + "".join(tr) + "</tbody></table></div>" + pg + nt)


def field(label, control, hint=""):
    return ('<div class="field"><label>' + label + "</label>" + control
            + (('<div class="hint">' + hint + "</div>") if hint else "") + "</div>")


def selects(label, options, value=None, minw="150px"):
    sel = value or options[0]
    opts = "".join('<option%s>%s</option>' % (" selected" if o == sel else "", o) for o in options)
    return ('<div class="field"><label>' + label + '</label><select class="input" style="min-width:'
            + minw + '">' + opts + "</select></div>")


def seg(label, options, on=0):
    return ('<div class="field"><label>' + label + '</label><div class="seg">'
            + "".join('<span class="%s">%s</span>' % ("on" if i == on else "", o)
                      for i, o in enumerate(options)) + "</div></div>")


def stat(label, value, formula=""):
    q = '<span class="qmark" title="%s">?</span>' % formula if formula else ""
    return ('<div class="stat"><div class="label">' + label + q + '</div><div class="v">'
            + value + "</div></div>")


def rows_block(items):
    return '<div class="rows">' + "".join(items) + "</div>"


def row(k, v):
    return '<div class="row"><span class="k">' + k + '</span><span class="num">' + v + "</span></div>"


def dotrow(status, text, right=""):
    return ('<div class="row"><span class="dot dot-' + status + '"></span><span>' + text + "</span>"
            + ('<span class="top-spacer"></span>' if right else "") + (right or "") + "</div>")


def spec(ids):
    body = "".join("<li>" + s + "</li>" for s in ids)
    return ('<section class="card" style="background:var(--bg-1)"><div class="card-h"><h2>规格注释</h2>'
            '<span class="sub">本页对应需求与用例</span></div><ul class="mono-sm" style="margin:0;'
            'padding-left:18px;line-height:1.8">' + body + "</ul></section>")


def modal_mock(title, lines, cta="确认发布", danger=False):
    return ('<div class="card" style="box-shadow:var(--sh-2);border-color:var(--line-2);max-width:520px">'
            '<div class="card-h"><h2>' + title + "</h2></div>"
            + rows_block(lines)
            + '<div class="row" style="margin-top:12px"><input type="checkbox" id="ck"><label for="ck" '
            'style="margin-left:8px;font-size:13px">我已确认口径与影响数字（必填勾选）</label></div>'
            + '<div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end">'
            + '<button class="btn">取消</button>'
            + '<button class="btn ' + ("btn-danger" if danger else "btn-primary") + '">' + cta + "</button></div></div>")


def states_mock():
    return '<div class="grid g4">' + "".join([
        '<div class="state"><h3>正常</h3>数据齐全，指标可 hover 查看口径</div>',
        '<div class="state"><h3>加载</h3><div class="sk skel-row" style="width:70%"></div>'
        '<div class="sk skel-row" style="width:90%"></div><div class="sk skel-row" style="width:55%"></div>'
        '<div class="hint">&gt;1.5s 显示预计 n 秒；&gt;10s 转后台任务</div></div>',
        '<div class="state"><h3>空态</h3>尚未创建模拟盘账户'
        '<div style="margin-top:8px"><button class="btn btn-sm btn-primary">创建账户</button> '
        '<span class="mono-sm">仅 role:pm 可见</span></div></div>',
        '<div class="state err"><h3>错误</h3>存储不可用（QUANT-O-001）'
        '<div class="mono-sm" style="margin-top:6px">trace_id=7f3a9c21 <button class="btn btn-sm">复制</button></div>'
        '<div style="margin-top:8px"><button class="btn btn-sm">重试</button> '
        '<span class="mono-sm">写操作按钮已禁用</span></div></div>',
    ]) + "</div>"


# ---------------------------------------------------------------- 数据
T0 = series_walk(760, 1.0, 0.175, 0.11, 7)
B0 = series_walk(760, 1.0, 0.145, 0.035, 21)
IC = series_walk(120, 0.055, 0.02, 0.0, 5)
IC_S = [(v - 0.055) for v in IC]


def dd(series):
    peak, out = -1e9, []
    for v in series:
        peak = max(peak, v)
        out.append((v / peak - 1) * 100)
    return out


def maxdd_info(series):
    d = dd(series)
    i = min(range(len(d)), key=lambda k: d[k])
    peak_i = max(range(i + 1), key=lambda k: series[k])
    return d[i], peak_i, i


def stats_of(series):
    n = len(series)
    total = series[-1] / series[0] - 1
    ann = (1 + total) ** (252.0 / n) - 1
    mx, peak_i, trough_i = maxdd_info(series)
    rets = [series[i] / series[i - 1] - 1 for i in range(1, n)]
    mean = sum(rets) / len(rets)
    vol = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252)
    return {"ann": ann * 100, "maxdd": mx, "peak": peak_i, "trough": trough_i,
            "sharpe": (ann - 0.015) / vol if vol else 0.0, "days": n}


def day_label(idx):
    """把序列下标映射为近似日历日标签（视觉稿用，非交易日历）。"""
    y, m, day = 2022, 1, 4
    for _ in range(idx):
        day += 1
        if day > 28:
            day, m = 1, m + 1
            if m > 12:
                m, y = 1, y + 1
    return "%d-%02d-%02d" % (y, m, day)


# ---------------------------------------------------------------- 页面
def p_index():
    nav_links = "".join(
        '<div class="card"><div class="card-h"><h2>%s</h2></div><ul style="margin:0;padding-left:18px;'
        'font-size:13px;line-height:1.9;color:var(--text-2)">%s</ul></div>'
        % (g, "".join('<li><a href="%s">%s</a></li>' % (h, l) for h, l, _b, _t in items))
        for g, items in NAV
    )
    palette = '<div class="grid g4">' + "".join(
        '<div class="card" style="padding:12px"><div style="height:44px;border-radius:var(--r-sm);background:%s"></div>'
        '<div class="mono-sm" style="margin-top:8px">%s</div><div class="hint">%s</div></div>'
        % (v, n, use) for n, v, use in [
            ("--brand-600", "#0F4C81", "导航激活 / 主按钮"),
            ("--market-up", "#D6453D", "涨（A股惯例=红）"),
            ("--market-down", "#1F9254", "跌（A股惯例=绿）"),
            ("--warn-600", "#B26A00", "PARTIAL / 降级 / WARN"),
            ("--err-600", "#B33771", "门禁 FAIL / 熔断 / 拒单"),
            ("--ok-600", "#2F8540", "校验通过（不用于行情）"),
            ("--text-1", "#1A1D22", "主文本 4.6:1 达 AA"),
            ("--bg-1", "#F5F7FA", "页面背景"),
        ]) + "</div>"
    comp = "".join([
        '<div class="card"><div class="card-h"><h2>涨跌双编码</h2></div>'
        + '<div class="row" style="gap:12px">' + delta(3.21) + delta(-1.08) + delta(0.0, digits=2)
        + '<span class="mono-sm">切换国际配色后仅换色，符号/箭头不变</span></div>'
        + '<div style="margin-top:12px">' + kpi("日收益", "+1.62%", delta(1.62, " pp"), "年化=∏(1+r)^(252/n)-1；水位 a7f3c1") + "</div></div>",
        '<div class="card"><div class="card-h"><h2>状态标签</h2></div><div class="row" style="flex-wrap:wrap;gap:6px">'
        + "".join([tag("pass", "ok"), tag("published", "info"), tag("PARTIAL", "warn"),
                   tag("LOOKAHEAD_FAIL", "err"), tag("draft"), tag("已失效")])
        + '</div><div class="hint">状态文案=中文语义 + 原始码 tooltip</div></div>',
        '<div class="card"><div class="card-h"><h2>按钮与禁用</h2></div>'
        + '<div class="row" style="gap:8px"><button class="btn btn-primary">发布信号</button>'
        + '<button class="btn btn-danger">解除熔断</button><button class="btn">取消</button>'
        + '<button class="btn btn-primary" disabled title="因 未来函数门禁 FAIL 被禁用">转信号发布</button></div>'
        + '<div class="hint">禁用由响应 can_publish 驱动，前端不复算判定（UI-02）</div></div>',
        '<div class="card"><div class="card-h"><h2>5 态矩阵</h2></div>' + states_mock() + "</div>",
    ])
    body = (
        '<div class="banner"><b>quant-pro 高保真可点击视觉稿</b>'
        '<span class="mono-sm">1440×900 基准 · 离线无 CDN · tokens.css 单一来源 · 由 prototype/build.py 生成</span></div>'
        + '<div class="grid g2">' + card("页面清单与导航", nav_links, "两级菜单按业务域分组")
        + card("设计令牌", palette, "UI-DESIGN §2") + "</div>"
        + '<div style="height:16px"></div>' + card("组件库预览", comp)
        + '<div style="height:16px"></div>'
        + card("如何用例对照", table(
            ["视觉稿页面", "对应 FR", "对应 TC", "关键校验点"],
            [["总览驾驶舱", "FR-U-01", "TC-U-02", "KPI 与 SQL 抽查一致"],
             ["数据质量 / 修正留痕", "FR-U-02", "TC-D-07/09", "原行保留，无直接编辑"],
             ["因子库 / AI 研究台", "FR-U-03", "TC-F-07, TC-A-05", "相关性>0.95 需确认"],
             ["回测运行详情", "FR-U-04", "TC-U-05, TC-B-20", "门禁面板 FAIL 锁发布"],
             ["当日信号与发布", "FR-G-01", "TC-G-01/02", "四项前置校验 + 二次确认"],
             ["对账与追溯", "FR-P-05", "TC-P-05/06", "无手工调整入口"],
             ["熔断状态", "FR-R-03", "TC-R-01/07", "仅拒新增买入，不强平"]],
            note_text="打开任意页面可点导航互跳；<code>python3 prototype/build.py</code> 重新生成，"
                      "<code>python3 prototype/shoot.py</code> 产出 shots/*.png 供文档嵌入。")
        )
    )
    return page("index.html", "视觉稿总览",
                "生产侧运行态的版式与口径展示基线；数字为演示占位，非回测结果",
                body, actions='<button class="btn btn-sm">切换主题</button><button class="btn btn-sm">导出 PDF</button>',
                crumb="设计资产 / 视觉稿")


def p_dashboard():
    ddv = dd(T0)
    st, sb = stats_of(T0), stats_of(B0)
    nav = card("组合净值 vs 基准（沪深300）",
               '<div class="legend" style="margin-bottom:8px"><span><i style="background:var(--chart-1)"></i>本组合</span>'
               '<span><i style="background:var(--chart-2)"></i>000300</span>'
               '<span class="mono-sm">样本 2022-01 → 2025-11 · %d 交易日 · 降采样阈值 5000 点（未触发）</span></div>'
               % st["days"]
               + line_chart([("本组合", "var(--chart-1)", False, T0), ("000300", "var(--chart-2)", True, B0)],
                            yfmt="%0.2f")
               + '<div class="card-h" style="margin:16px 0 4px"><h2>回撤</h2><span class="sub">副轴，% </span></div>'
               + area_line(ddv)
               + '<div class="stats">'
               + stat("年化收益", '<span class="up num">%+.2f%%▲</span>' % st["ann"],
                      "(1+total)^(252/n)-1")
               + stat("Sharpe", '<span class="num">%0.2f</span>' % st["sharpe"], "(ann-rf)/ann_vol, rf=1.5%")
               + stat("最大回撤", '<span class="neg num">%0.2f%%</span>' % st["maxdd"], "max(1-nav/cummax)")
               + stat("峰 → 谷", '<span class="num">%s → %s</span>' % (day_label(st["peak"]), day_label(st["trough"])),
                      "峰谷日期取自 cummax 与最低点")
               + "</div>"
               + '<div class="row" style="gap:8px;margin-top:10px">'
               + '<span class="top-spacer"></span><button class="btn btn-sm">导出 PNG</button>'
               + '<button class="btn btn-sm">复制数字</button><a class="btn btn-sm" href="#tbl-positions">数据表格替代</a></div>',
               right='<div class="seg"><span>1M</span><span>3M</span><span class="on">3Y</span><span>全部</span></div>')
    sig = card("今日信号",
               rows_block([
                   dotrow("ok", "状态 published", '<span class="mono-sm">run_id=sig-20261120-01</span>'),
                   row("换手（单边）", "38.2%"), row("预估成本", "1.83 万"),
                   row("调仓标的", "买 11 / 卖 9"),
               ])
               + '<div style="height:12px"></div>'
               + table(["标的", "Δ权重", "方向"],
                       [["600519 贵州茅台", delta(2.1), "买"],
                        ["000858 五粮液", delta(1.4), "买"],
                        ["300750 宁德时代", delta(1.1), "买"],
                        ["601398 工商银行", delta(-1.9), "卖"]],
                       ["l", "r", "l"],
                       note_text='<a href="signals.html">查看完整信号与归因分解 →</a>'),
               "2026-11-20")
    risk = card("风控状态",
                '<div class="banner banner-warn" style="margin-bottom:12px"><b>当前回撤 -15.42%</b>'
                '<span class="mono-sm">熔断阈值 -20.00%（R-DRAWDOWN-01）</span></div>'
                + '<div class="progress"><i style="width:77%;background:var(--warn-600)"></i></div>'
                + '<div class="hint">已用水位 77%（15.42 / 20.00）；触发后仅拒绝新增买入</div>'
                + '<div style="height:12px"></div>'
                + rows_block([dotrow("err", "未确认风控事件 3 项",
                           '<a class="btn btn-sm" href="risk.html">确认</a>'),
                             dotrow("idle", "熔断：未激活")]),
                "role:risk 可解除")
    health = card("数据与健康",
                  rows_block([
                      dotrow("ok", "daily_bar 2026-11-20 · 5,312 行"),
                      dotrow("warn", "fundamental_pit 缺口 1 交易日",
                             '<a class="btn btn-sm" href="data-jobs.html">补数</a>'),
                      dotrow("ok", "阻断 issue 0"),
                      dotrow("err", "quality_check 上次失败（3 次重试）",
                             '<a class="btn btn-sm" href="data-quality.html">查看</a>'),
                  ])
                  + '<div style="height:10px"></div>'
                  + table(["作业", "状态", "行数", "耗时"],
                          [["fetch_bars_daily", '<span class="dot dot-ok"></span> SUCCESS', "5,312", "3m21s"],
                           ["factor_compute", '<span class="dot dot-ok"></span> SUCCESS', "63,744", "9m02s"],
                           ["signal_generate", '<span class="dot dot-ok"></span> SUCCESS', "30", "12s"],
                           ["reconcile", '<span class="dot dot-warn"></span> PARTIAL', "—", "4s"]],
                          ["l", "l", "r", "r"]),
                  "store=Timescale")
    todo = card("待办（按角色）",
                rows_block([
                    '<div class="row"><span class="tag tag-err">S2</span><span>回测 run-a83f 体检 FAIL，需复核 OOS 区间</span></div>',
                    '<div class="row"><span class="tag tag-warn">S2</span><span>mom_20 与 mom_60 相关性 0.96，等待确认</span></div>',
                    '<div class="row"><span class="tag">S3</span><span>财务因子 PIT 缺公告日，报告已标黄</span></div>',
                ]), "researcher")
    pos = '<section class="card" id="tbl-positions"><div class="card-h"><h2>持仓 Top 5（数据表格替代）</h2>' \
          '<span class="sub">aria 图表等价物</span></div>' \
          + table(["标的", "数量", "可售(T+1)", "市值", "权重", "浮动盈亏", "行业"],
                  [["600519 贵州茅台", "30,000", "0/30,000", "5,082.60 万", "10.00%", delta(4.31), "食品饮料"],
                   ["000858 五粮液", "120,000", "120,000", "2,015.40 万", "9.62%", delta(1.08), "食品饮料"],
                   ["300750 宁德时代", "55,000", "55,000", "1,512.30 万", "8.31%", delta(-2.14), "电力设备"],
                   ["601398 工商银行", "900,000", "900,000", "1,124.10 万", "6.42%", delta(0.32), "银行"],
                   ["002415 海康威视", "310,000", '<span class="mono-sm">非整手</span>', "985.20 万", "5.91%", delta(-0.87), "电子"]],
                  ["l", "r", "r", "r", "r", "r", "l"],
                  pager_total=1248) + "</section>"
    body = (
        '<div class="grid g4">'
        + kpi("组合净值", "%0.4f" % (T0[-1] / T0[0]), delta(1.62), "nav=(cash+Σmv)/初始，6 位小数")
        + kpi("当日收益", "+1.62%", delta(0.21, " pp"), "r=adj_close_t/adj_close_{t-1}-1")
        + kpi("最大回撤", '<span class="neg num">%0.2f%%</span>' % st["maxdd"],
              "修复 %d 交易日" % (st["days"] - st["trough"]), "max(1-nav/cummax(nav))")
        + kpi("超额收益（年化）", "%+.2f%%" % (st["ann"] - sb["ann"]),
              '<span class="num">0.62 IR</span>', "IR=年化超额/跟踪误差")
        + "</div><div style=\"height:16px\"></div>"
        + '<div class="grid g-2-1">' + nav + '<div class="grid">' + sig + risk + "</div></div>"
        + '<div style="height:16px\"></div>'
        + '<div class="grid g2">' + health + pos + "</div>"
        + '<div style="height:16px"></div>' + todo
        + '<div style="height:16px"></div>'
        + spec(["FR-U-01 总览四要素：净值/信号/风控/新鲜度",
                "UI-01 指标 hover 口径气泡（公式 + 区间 + data_version）",
                "UI-03 缺口与失败在侧栏徽标与待办同步，不藏二级页",
                "TC-U-02 KPI 数字与 SQL 抽查一致；TC-X-02 无 NaN/null 渲染"])
    )
    return page("dashboard.html", "总览驾驶舱",
                "净值、回撤、今日信号、风控水位与数据健康的一屏视图",
                body, actions='<a class="btn btn-sm" href="backtest.html">发起回测</a>'
                '<button class="btn btn-sm">刷新</button>', crumb="概览 / 总览驾驶舱")


def p_data_quality():
    k = '<div class="grid g4">' + kpi("覆盖率", "99.87%", "阈值 99%", "is_final 标的数 / 应交易标的数") \
        + kpi("阻断 issue", '<span class="down">7</span>', None, "blocking=true，下游作业将被跳过") \
        + kpi("异常行", "1,204", "0.023%", "按 data_issue.kind 分类") \
        + kpi("双源差异", '<span class="num flat">0.008%</span>', None, "东财 vs 同花顺，阈值 0.01%") + "</div>"
    tabs = '<div class="tabs"><span class="on">异常明细</span><span>按类型汇总</span><span>阻断项</span></div>'
    issues = table(
        ["交易日", "标的", "字段", "类型", "详情", "阻断", "状态", "操作"],
        [["2026-11-20", "000031 深房 B", "close", "PRICE_NONPOSITIVE", "close=0.00", tag("是", "err"),
          tag("open"), '<button class="btn btn-sm">原值</button> <button class="btn btn-sm">标记 ignored</button>'],
         ["2026-11-20", "688xxx 某科", "amount", "AMT_SELF_INCONSISTENT", "amount/(v) 偏离 3σ", tag("是", "err"),
          tag("open"), '<button class="btn btn-sm">原值</button>'],
         ["2026-11-19", "301xxx 某创", "adj_factor", "ADJ_FACTOR_SUSPECT", "跳变 +24.1% 无除权事件", tag("是", "err"),
          tag("open"), '<a class="btn btn-sm" href="data-sources.html">双源对照</a>'],
         ["2026-11-19", "600xxx 某股", "-", "LOW_COVERAGE", "当日截面 88 只 < 100", tag("是", "err"), tag("open"),
          '<a class="btn btn-sm" href="data-jobs.html">补数</a>'],
         ["2026-11-18", "002xxx 某股", "volume", "DUPLICATE_KEY", "重复主键已 upsert 去重", tag("否"), tag("ignored"),
          '<span class="mono-sm">理由：源端重发</span>']],
        ["l", "l", "l", "l", "l", "l", "l", "l"], pager_total=1204,
        note_text="筛选默认 <code>阻断=是</code>；标记 ignored 需理由且仅 role:data 可用（TC-D-07）。")
    amend = card("修正留痕（只追加，原行保留）",
                 table(["时间", "交易日", "标的", "字段", "原值", "新值", "操作人", "stale 影响"],
                       [["2026-11-18 20:12", "2026-11-15", "600xxx", "close", "12.34", "13.24", "hegan",
                         '<a href="backtest-runs.html">3 个 run</a>'],
                        ["2026-11-11 09:40", "2026-11-10", "002xxx", "volume", "0", "1,234,500", "hegan", "—"]],
                       ["l", "l", "l", "l", "r", "r", "l", "l"],
                       note_text="页面无直接编辑行情入口（ADR-013 / TC-D-09）；<code>新增修正</code> 对话框要求理由必填。"),
                 "共 41 条")
    body = ('<div class="filters">' + seg("区间", ["近 5 日", "近 30 日", "自定义"], on=0)
            + selects("类型", ["全部", "PRICE_NONPOSITIVE", "ADJ_FACTOR_SUSPECT", "LOW_COVERAGE", "DUPLICATE_KEY"], minw="210px")
            + selects("阻断", ["全部", "仅阻断", "非阻断"])
            + '<button class="btn btn-sm">导出 CSV</button><span class="top-spacer"></span>'
            + '<button class="btn btn-sm btn-primary">标记 ignored</button></div>'
            + k + '<div style="height:16px"></div>' + tabs + card("异常明细", issues, "kind × 阻断项")
            + '<div style="height:16px"></div>' + amend + '<div style="height:16px"></div>'
            + spec(["FR-D-07 六类校验 + blocking 阻断下游",
                    "FR-D-08 修正必须留痕，禁止静默 UPDATE（TC-D-09）",
                    "UI-03 阻断项在侧栏徽标与待办默认可见",
                    "TC-U-03 点击 issue 可定位到原值与双源对照"]))
    return page("data-quality.html", "数据质量看板", "缺失、重复、越界、自洽、复权可疑、跳变与覆盖率",
                body, actions='<a class="btn btn-sm" href="data-jobs.html">触发补数</a>',
                crumb="数据 / 质量")


def p_research_factors():
    rows = [
        ["mom_20", "动量 20 日", "+1", '<span class="num">0.041</span>', "0.62", "3.11", "61.2%",
         delta(4.81), "买10→卖1", tag("单调", "ok"), '<span class="down num">0.96</span>', tag("待确认", "warn")],
        ["mom_60", "动量 60 日", "+1", "0.035", "0.55", "2.74", "58.0%", delta(3.92), "买10→卖1",
         tag("单调", "ok"), "0.96", tag("启用", "ok")],
        ["vol_60", "60 日波动率", "-1", "-0.022", "-0.41", "-2.03", "44.1%", delta(-1.22), "倒序",
         tag("倒序", "warn"), "0.31", tag("启用", "ok")],
        ["ep", "盈利收益率 TTM", "+1", "0.028", "0.48", "2.40", "56.3%", delta(2.88), "买10→卖1",
         tag("单调", "ok"), "0.27", tag("启用", "ok")],
        ["size", "对数总市值", "-1", "0.019", "0.33", "1.65", "52.8%", delta(2.10), "买10→卖1",
         tag("单调", "ok"), "0.44", tag("启用", "ok")],
        ["crowding", "行业拥挤度", "-1", "0.011", "0.18", "0.91", "50.2%", delta(0.77), "平坦",
         tag("非单调", "err"), "0.12", tag("观察", "warn")],
        ["roe_ttm", "净资产收益率 TTM", "+1", "0.024", "0.40", "2.02", "54.7%", delta(2.31), "买10→卖1",
         tag("单调", "ok"), "0.35", tag("启用", "ok")],
        ["rev_5", "5 日反转", "+1", "0.031", "0.51", "2.57", "57.4%", delta(3.15), "买10→卖1",
         tag("单调", "ok"), "0.22", tag("启用", "ok")],
    ]
    tbl = table(["因子", "名称", "方向", "IC 均值", "ICIR", "t 值", "IC&gt;0 占比", "Top-Bottom 年化",
                 "分层", "单调性", "最大相关", "状态"],
                rows, ["l", "l", "l", "r", "r", "r", "r", "r", "l", "l", "r", "l"], pager_total=24,
                note_text="点击行进入详情（IC 序列 / 分层柱 / 相关性矩阵 / 依赖图）。排序与分页走服务端。")
    detail = card("因子详情：mom_20",
                  '<div class="legend" style="margin-bottom:6px"><span><i style="background:var(--chart-1)"></i>IC 序列（月度）</span>'
                  '<span class="mono-sm">Spearman vs T+1 月收益 · 窗口 24m · 120 期</span></div>'
                  + line_chart([("IC", "var(--chart-1)", False, IC_S)], height=140, yfmt="%+0.3f")
                  + '<div class="grid g2" style="margin-top:14px">'
                  + '<div><div class="card-h"><h2>5 分层年化（%）</h2></div>'
                  + bars([1.8, 2.9, 3.6, 5.1, 6.6], ["Q1", "Q2", "Q3", "Q4", "Q5"], height=150, color="var(--chart-1)")
                  + '<div class="hint">单调递增 → 通过；分层收益须与 SQL 独立实现一致（TC-F-06）</div></div>'
                  + '<div><div class="card-h"><h2>因子相关性矩阵（上三角）</h2></div>'
                  + corr_matrix(["mom_20", "mom_60", "rev_5", "vol_60", "ep", "size", "roe"])
                  + '<div class="hint">红框=相关性 &gt; 0.95，注册新因子时须人工确认（FR-F-05 / TC-F-07）</div></div></div>',
                  right='<button class="btn btn-sm btn-primary">重算评估</button><button class="btn btn-sm">依赖图</button>')
    body = ('<div class="filters">' + selects("评估窗口", ["6m", "12m", "24m", "全部"])
            + seg("方向", ["全部", "越大越好", "越小越好"])
            + '<div class="field"><label>搜索</label><input class="input" placeholder="因子 id / 名称"></div>'
            + '<button class="btn btn-sm">只看单调</button><span class="top-spacer"></span>'
            + '<a class="btn btn-sm btn-primary" href="research-ai-lab.html">注册新因子（研究台）</a></div>'
            + card("因子库", tbl, "24 个因子") + '<div style="height:16px"></div>' + detail
            + '<div style="height:16px"></div>'
            + spec(["FR-F-03 处理链=剔除→winsorize→z-score→方向，唯一实现",
                    "FR-F-05 相关性 0.96 触发确认，不静默新增",
                    "FR-F-06 walk-forward 权重窗口 [T-24M, T-1]（TC-F-08 变异必拦）",
                    "TC-F-04 截面 < 100 只当日不产出因子并记 LOW_COVERAGE"]))
    return page("research-factors.html", "因子库", "IC / ICIR / 分层单调性 / 相关性 与因子详情",
                body, actions='<a class="btn btn-sm" href="backtest.html">用该因子跑回测</a>',
                crumb="研究 / 因子库")


def p_backtest():
    form = card("回测参数",
                '<div class="grid g2">'
                + field("策略", '<select class="input"><option>s2_multifactor · 多因子月度 v1</option>'
                        '<option>s1_trend · 沪深300 双均线 v1</option><option>s3_rotation · 行业轮动 v1</option></select>')
                + field("区间（训练）", '<input class="input" value="2016-01-04 → 2021-12-31">'
                        '<div class="hint">调仓日自动顺延到交易日：月度 72 次</div>')
                + field("区间（留出 OOS）", '<input class="input" value="2022-01-04 → 2025-12-31">'
                        '<div class="hint">与训练区间重叠时禁止提交</div>')
                + field("universe", '<select class="input"><option>ALL_A（含退市，5,312 只）</option>'
                        '<option>000300 + 000905</option><option>自定义列表</option></select>'
                        '<div class="hint">预估耗时 62s；数据水位检查已就绪 ✓</div>')
                + field("佣金 bp（最低 5 元）", '<input class="input num" value="2.5">')
                + field("印花税 bp（卖出单边）", '<input class="input num" value="5">')
                + field("过户费 bp", '<input class="input num" value="0.1">')
                + field("滑点 bp", '<input class="input num" value="5">'
                        '<div class="hint">敏感性将自动跑 0 / 5 / 10bp 三档</div>')
                + field("基准", '<select class="input"><option>000300</option><option>000905</option></select>')
                + field("随机种子", '<input class="input num" value="7">')
                + field("单票权重上限", '<input class="input num" value="10%">')
                + field("行业偏离上限", '<input class="input num" value="8%">')
                + "</div>"
                + '<div class="banner banner-warn" style="margin-top:14px"><b>成本口径提醒</b>'
                '<span class="mono-sm">高换手策略在 0bp 档收益不可用于决策，需以 5/10bp 档为准</span></div>'
                + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">'
                + '<button class="btn">保存为草稿</button>'
                + '<button class="btn btn-primary">发起回测</button></div>',
                "schema 动态渲染（ParamForm）")
    prog = card("运行中：run-a83f（s2_multifactor v1）",
                '<div class="progress"><i style="width:64%"></i></div>'
                '<div class="row" style="margin-top:8px"><span class="mono-sm">已处理 487 / 760 交易日 · 用时 39s · ETA 22s</span>'
                '<span class="top-spacer"></span><button class="btn btn-sm">取消</button></div>',
                "JobProgress · 指数退避轮询 1→5s，离开页面不中断")
    metrics = '<div class="grid g4">' + "".join([
        kpi("年化收益（OOS）", '<span class="up num">+9.21%</span>', None, "(1+total)^(252/n)-1"),
        kpi("Sharpe（OOS）", '<span class="num">0.71</span>', None, "(ann-rf)/ann_vol, rf=1.5%"),
        kpi("最大回撤", '<span class="neg num">-18.06%</span>', "2024-01-08 → 2024-08-19", "max(1-nav/cummax)"),
        kpi("Calmar", '<span class="num">0.51</span>', None, "ann/max_dd，max_dd 为损失类指标用 err 色"),
        kpi("年化换手", '<span class="num">412%</span>', None, "Σ单边成交额/mean(mv)/年"),
        kpi("成本占毛收益", '<span class="num">34.1%</span>', None, "Σ(fee+滑点)/毛收益 ≤ 40% 红线"),
        kpi("信息比率", '<span class="num">0.62</span>', None, "年化超额/TE"),
        kpi("Beta / Alpha", '<span class="num">0.83 / +5.4%</span>', None, "OLS(r_p-rf ~ r_b-rf)"),
    ]) + "</div>"
    gate = card("未来函数门禁（FR-B-13）",
                '<div class="checks">'
                + '<div class="check pass"><span class="n">LAG-1 前视替换</span>'
                  '<span class="mono-sm">T+1..T+5 置 NaN 重跑</span><span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
                + '<div class="check pass"><span class="n">LAG-2 财报时点</span>'
                  '<span class="mono-sm">ann_date ≤ T 全覆盖</span><span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
                + '<div class="check warn"><span class="n">LAG-3 复权因子</span>'
                  '<span class="mono-sm">214 行使用当日抓取因子（免费源限制）</span>'
                  '<span class="top-spacer"></span>' + tag("WARN 已标黄", "warn") + "</div>"
                + '<div class="check pass"><span class="n">LAG-4 窗口右端</span>'
                  '<span class="mono-sm">rolling min_periods=n</span><span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
                + '<div class="check fail"><span class="n">LAG-5 退市持仓</span>'
                  '<span class="mono-sm">3 只退市标的持仓未取清算价 → NAV 高估</span>'
                  '<span class="top-spacer"></span>' + tag("FAIL", "err") + "</div>"
                + "</div>"
                + '<div class="hint">任一 FAIL ⇒ 该 run 标记 LOOKAHEAD_FAIL，发布按钮由后端 can_publish=false 锁定'
                  '（TC-B-20..24 变异测试必须全部拦下）</div>', "5 项自动检查")
    checklist = card("过拟合体检表（FR-A-04）",
                     table(["项", "阈值", "本例", "判定"],
                           [["OOS vs IS Sharpe", "OOS ≥ 0.3 且 ≥ 0.3×IS", "0.71 / 1.34", tag("pass", "ok")],
                            ["参数扰动 ±20%", "不符号翻转、跌幅 ≤ 50%", "0.55~0.79", tag("pass", "ok")],
                            ["5 分层单调性", "必须单调", "单调递增", tag("pass", "ok")],
                            ["成本占毛收益", "≤ 40%", "34.1%", tag("pass", "ok")],
                            ["IC 衰减", "20 期后不异常放大", "正常衰减", tag("pass", "ok")],
                            ["与已有因子相关性", "≤ 0.95", "0.96", tag("需确认", "warn")]],
                           ["l", "l", "r", "l"],
                           note_text="FAIL 项存在时不允许进入信号发布与模拟盘（引擎层强制，非前端提示）。"))
    sens = card("成本敏感性（强制三档）",
                table(["滑点", "年化", "Sharpe", "最大回撤", "换手", "成本占比"],
                      [["0 bp", '<span class="up num">+11.83%</span>', "0.92", '<span class="neg num">-17.6%</span>', "412%", "18.4%"],
                       ["5 bp", '<span class="up num">+9.21%</span>', "0.71", '<span class="neg num">-18.1%</span>', "412%", "34.1%"],
                       ["10 bp", '<span class="up num">+6.44%</span>', "0.50", '<span class="neg num">-18.9%</span>', "412%", '<span class="neg num">48.7%</span>']],
                      ["l", "r", "r", "r", "r", "r"],
                      note_text="随滑点非单调下降时自动标红；>40% 成本占比触发体检 FAIL。"))
    rej = card("拒单分析",
               '<div class="grid g2">'
               + table(["原因码", "笔数", "占比"],
                       [["LIMIT_UP_ONE_PU", "148", "22.1%"], ["SUSPENDED", "121", "18.1%"],
                        ["CASH_SHORT", "44", "6.6%"], ["SELLABLE_SHORT", "31", "4.6%"],
                        ["RISK_REJECT", "18", "2.7%"], ["SKIPPED_TURNOVER", "9", "1.3%"]],
                       ["l", "r", "r"],
                       note_text="每笔均落 backtest_order.reject_reason，无静默丢弃（TC-B-08）。")
               + '<div><div class="card-h"><h2>原因分布</h2></div>'
               + bars([148, 121, 44, 31, 18, 9], ["涨停", "停牌", "现金", "T+1", "风控", "换手"], height=170) + "</div></div>",
               "先卖后买 · 整手取整")
    nav = card("净值与归因",
               '<div class="legend" style="margin-bottom:6px"><span><i style="background:var(--chart-1)"></i>OOS 本组合</span>'
               '<span><i style="background:var(--chart-2)"></i>000300</span>'
               '<span class="mono-sm">区间 2022-01 → 2025-11 · 样本外</span></div>'
               + line_chart([("本组合", "var(--chart-1)", False, T0), ("000300", "var(--chart-2)", True, B0)], height=210)
               + '<div class="grid g3" style="margin-top:14px">'
               + '<div><div class="card-h"><h2>Brinson 归因（%）</h2></div>'
               + bars([1.9, 4.1, 0.6], ["配置", "选股", "交互"], height=150, width=360)
               + '<div class="hint">三项之和 ≈ 超额（误差 < 1e-4，TC-B-17）</div></div>'
               + '<div><div class="card-h"><h2>月度收益热力</h2></div>' + month_heat([2022, 2023, 2024, 2025]) + "</div>"
               + '<div><div class="card-h"><h2>回撤</h2></div>' + area_line(dd(T0), height=110) + "</div></div>",
               right='<button class="btn btn-sm">导出 HTML</button><button class="btn btn-sm">JSON</button>'
                     '<button class="btn btn-sm">订单 CSV</button>')
    publish = ('<div class="card" style="border-color:var(--err-600)"><div class="card-h">'
               '<h2>发布联动</h2><span class="sub">后端字段驱动</span></div>'
               '<div class="row" style="gap:8px"><button class="btn btn-primary" disabled '
               'title="lookahead_status=FAIL：LAG-5 退市清算价缺失">转信号发布</button>'
               '<span class="tag tag-err">can_publish=false</span>'
               '<span class="mono-sm">blocking_reasons=["QUANT-B-011 LAG-5"]</span>'
               '<span class="top-spacer"></span><a class="btn btn-sm" href="signals.html">查看发布校验</a></div></div>')
    body = ('<div class="grid g-2-1">' + form + prog
            + '<div class="grid">' + gate + publish + "</div></div>"
            + '<div style="height:16px"></div>' + metrics + '<div style="height:16px"></div>'
            + nav + '<div style="height:16px"></div>'
            + '<div class="grid g2">' + sens + rej + "</div>"
            + '<div style="height:16px"></div>' + checklist
            + '<div style="height:16px"></div>'
            + spec(["config_hash 显示在 URL，同 hash 重跑逐值一致（TC-B-15）",
                    "P1 阶段该页数字来自 CLI/HTML 报告，P2 起为运行态（UI-DESIGN §12）",
                    "UI-05 危险/成本类参数需影响提示；训练/留出重叠禁止提交",
                    "TC-U-04 提交→202→轮询→结果；可取消；TC-X-05 首屏 < 2s"]))
    return page("backtest.html", "回测：发起与运行详情", "参数表单、进度、五组指标、门禁与体检、敏感性与拒单",
                body, actions='<a class="btn btn-sm" href="backtest-runs.html">回测记录</a>'
                '<a class="btn btn-sm" href="index.html">对比模式</a>', crumb="回测 / 发起与运行详情")


def p_signals():
    checks = ('<section class="card"><div class="card-h"><h2>发布前置校验</h2>'
              '<span class="sub">四项任一 FAIL 即 422，状态停留 draft</span></div><div class="checks">'
              + '<div class="check pass"><span class="n">数据新鲜度</span>'
                '<span class="mono-sm">is_final 覆盖 99.87% ≥ 99%</span><span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
              + '<div class="check fail"><span class="n">阻断 issue</span>'
                '<span class="mono-sm">blocking=7（LOW_COVERAGE ×1 影响 3 个调仓标的）</span>'
                '<span class="top-spacer"></span>' + tag("FAIL", "err")
                + '<a class="btn btn-sm" href="data-quality.html">定位</a></div>'
              + '<div class="check fail"><span class="n">未来函数门禁</span>'
                '<span class="mono-sm">来源 run-a83f lookahead_status=FAIL</span>'
                '<span class="top-spacer"></span>' + tag("FAIL", "err")
                + '<a class="btn btn-sm" href="backtest.html">门禁详情</a></div>'
              + '<div class="check pass"><span class="n">风控预检</span>'
                '<span class="mono-sm">0 命中（单票 ≤10%、行业偏离 5.2% ≤8%）</span>'
                '<span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
              + "</div>"
              + '<div style="display:flex;gap:8px;align-items:center;margin-top:12px">'
              + '<button class="btn btn-primary" disabled title="前置校验未通过（后端 can_publish=false）">发布信号</button>'
              + '<button class="btn">重新校验</button>'
              + '<span class="mono-sm">当前状态 draft · run_id=sig-20261120-01</span></div></section>')
    items = card("目标组合（2026-11-20，月度调仓）",
                 table(["标的", "目标权重", "当前权重", "Δ", "方向", "预估成交", "归因分解"],
                       [["600519 贵州茅台", "10.00%", "8.20%", delta(1.8), "买", "24,000 股 @ 开盘",
                         '<span class="mono-sm">mom +0.9 / ep +0.4 / size +0.5</span>'],
                        ["000858 五粮液", "9.40%", "8.00%", delta(1.4), "买", "96,000 股", "mom +0.7 / roe +0.6"],
                        ["300750 宁德时代", "8.10%", "7.00%", delta(1.1), "买", "41,000 股", "mom +1.2 / rev −0.1"],
                        ["601398 工商银行", "6.40%", "8.30%", delta(-1.9), "卖", "180,000 股", "ep −1.1 / vol −0.8"],
                        ["002594 比亚迪", "5.20%", '<span class="mono-sm">—</span>', '<span class="up num">+5.20%▲</span>', "买",
                         "31,000 股", "mom +2.0 / 行业轮动 +1.4"],
                        ["000031 深房 B", '<span class="mono-sm">0.00%</span>', "0.90%", delta(-0.9), "卖",
                         '<span class="tag tag-err">不可成交</span>',
                         '<span class="mono-sm">SUSPENDED 停牌，顺延</span>'],
                        ["688xxx 某科", '<span class="mono-sm">—</span>', "1.20%", delta(-1.2), "卖",
                         '<span class="tag tag-warn">部分成交</span>', "SKIPPED_TURNOVER（换手上限 60%）"]],
                       ["l", "r", "r", "r", "l", "r", "l"],
                       note_text="权重合计 98.60% + 现金 1.40%（容差 1e-6，TC-G-04）；"
                                 "被拒标的保留在当前列，不静默消失。"),
                 "买入按 T+1 开盘成交，本表为目标态")
    summary = card("换手与成本摘要",
                   rows_block([
                       row("单边换手", "38.2%"), row("双边换手", "71.5%"),
                       row("预估成本（5bp 档）", "1.83 万"),
                       row("其中佣金 / 印花 / 过户 / 滑点", "0.44 / 0.36 / 0.02 / 1.01 万"),
                       row("风控命中", "0 项"),
                   ])
                   + '<div class="hint">来源 <a href="backtest.html">run-a83f</a> · 策略版本 s2_multifactor v1 · '
                     '因子快照 12 个 · data_version a7f3c1（TC-G-06 可追溯）</div>')
    hist = card("发布历史与不可逆",
                table(["交易日", "状态", "换手", "操作人", "时间", "操作"],
                      [["2026-11-20", tag("draft"), "38.2%", "张研究员", "19:46", "—"],
                       ["2026-10-20", tag("published", "info"), "41.9%", "李经理", "10-20 20:02",
                        '<a class="btn btn-sm">撤回（需原因）</a>'],
                       ["2026-09-18", tag("superseded"), "36.4%", "李经理", "09-18 20:05", '<span class="mono-sm">被 09-20 版取代</span>']],
                      ["l", "l", "r", "l", "l", "l"],
                      note_text="已发布不可修改，只能被新版本取代或撤回（TC-G-02）。"))
    body = checks + '<div style="height:16px"></div>' + '<div class="grid g-2-1">' + items
    body += '<div class="grid">' + summary + hist + "</div></div>"
    body += '<div style="height:16px"></div>' + card("二次确认对话框（发布态预览）",
              modal_mock("确认发布 2026-11-20 信号",
                         [row("权重合计", "98.60% + 现金 1.40%"), row("单边换手", "38.2%"),
                          row("预估成本（5bp）", "1.83 万"), row("风控命中", "0 项；行业偏离 5.2% ≤ 8%"),
                          row("下游影响", "模拟盘次日订单将按此目标生成（不可逆）")],
                         danger=False),
              "含影响数字，非泛化「确定吗」（UI-05 / TC-U-08）")
    body += '<div style="height:16px"></div>' + spec([
        "FR-G-03 四项前置校验由服务端返回，FAIL 时按钮禁用且给修复链接",
        "FR-G-02 发布后只读锁；撤回必须带原因与操作人",
        "TC-G-01 校验不过 → 422 + 原因清单；TC-U-08 无 confirm 参数 → 422",
        "UI-11 字段缺失显示「接口未提供」诊断条，不前端造数"])
    return page("signals.html", "当日信号与发布", "目标组合、前置校验、换手成本与不可逆发布流",
                body, actions='<button class="btn btn-sm">生成草稿</button>',
                crumb="信号 / 当日")


def p_paper():
    k = '<div class="grid g4">' + kpi("总资产", "1,042,600.00", delta(0.42), "cash + Σmv") \
        + kpi("净值", "1.0426", delta(0.42), "总资产 / 初始 100 万") \
        + kpi("现金", "86,420.00", None, "= Σ paper_ledger.amount（一致性指示）") \
        + kpi("当日损益", '<span class="up num">+4,312.00▲</span>', None, "含浮盈与费用") + "</div>"
    consist = ('<div class="banner" style="border-color:var(--ok-600);background:#EAF4EC">'
               '<b>现金 = Σ 流水</b><span class="mono-sm">86,420.00 = 86,420.00 一致 ✓</span>'
               '<span class="top-spacer"></span><a class="btn btn-sm" href="paper-recon.html">对账详情</a></div>')
    pos = card("持仓",
               table(["标的", "数量", "可售(T+1)", "成本价", "连续成本", "市值", "浮动盈亏", "权重", "行业"],
                     [["600519 贵州茅台", "300", '<span class="num">0/300</span>', "1,680.00", "1,540.22",
                       "50.83 万", '<span class="up num">+4.31%▲</span>', "10.00%", "食品饮料"],
                      ["000858 五粮液", "1,200", "1,200", "132.40", "128.10", "20.15 万", '<span class="up num">+1.08%▲</span>', "9.62%", "食品饮料"],
                      ["300750 宁德时代", "550", "550", "228.60", "225.10", "15.12 万", '<span class="down num">-2.14%▼</span>', "8.31%", "电力设备"],
                      ["601398 工商银行", "9,000", "9,000", "6.24", "6.20", "11.24 万", '<span class="up num">+0.32%▲</span>', "6.42%", "银行"],
                      ["002415 海康威视", "3,100", '<span class="mono-sm">非整手 3,100</span>', "31.20", "30.90",
                       "9.85 万", '<span class="down num">-0.87%▼</span>', "5.91%", "电子"]],
                     ["l", "r", "r", "r", "r", "r", "r", "r", "l"],
                     note_text="可售列形态 <code>0/300</code> 表示当日买入不可卖（T+1，TC-B-09）；"
                               "权重合计 96.4% + 现金 8.3%（含四舍五入）。"))
    orders = card("订单与拒单（默认只看异常）",
                  table(["交易日", "标的", "方向", "委托", "成交", "价格", "费用", "状态", "原因"],
                        [["2026-11-20", "600519", "买", "300", "300", "1,680.00", "156.30", tag("filled", "ok"), "—"],
                         ["2026-11-20", "000031", "卖", "1,000", "0", "—", "—", tag("rejected", "err"),
                          '<span title="SUSPENDED">停牌无法成交</span> <span class="mono-sm">SUSPENDED</span>'],
                         ["2026-11-19", "301xxx", "买", "2,000", "0", "—", "—", tag("rejected", "err"),
                          '<span title="LIMIT_UP_ONE_PU">一字涨停无法买入</span>'],
                         ["2026-11-19", "688xxx", "卖", "1,500", "600", "48.20", "18.40", tag("partial", "warn"),
                          '<span title="SKIPPED_TURNOVER">换手上限裁剪</span>'],
                         ["2026-11-18", "002xxx", "买", "5,000", "0", "—", "—", tag("rejected", "err"),
                          '<span title="CASH_SHORT">现金不足（整手后为 0）</span>']],
                        ["l", "l", "l", "r", "r", "r", "r", "l", "l"], pager_total=2148,
                        note_text="原因双列：中文语义 + 原始码 tooltip；无静默丢弃（FR-B-05）。"))
    ledger = card("流水（只追加）",
                  table(["时间", "类型", "标的", "数量", "金额", "余额", "来源"],
                        [["11-20 09:31", "trade", "600519", "300", "-504,000.00", "86,420.00", "sig-20261120-01"],
                         ["11-20 09:31", "fee", "600519", "—", "-156.30", "86,420.00", "佣金+过户"],
                         ["11-20 15:00", "mark", "全部", "—", "+4,312.00", "—", "日终估值"],
                         ["11-19 09:30", "reverse", "002xxx", "200", "+9,840.00", "—", "冲正（反向记录，非 UPDATE）"]],
                        ["l", "l", "l", "r", "r", "r", "l"],
                        note_text="余额由流水推导；不存在无来源的「调整」流水（TC-P-06 红线）。"))
    body = k + '<div style="height:16px"></div>' + consist + '<div class="grid g-2-1">' + pos + orders + "</div>" \
        + '<div style="height:16px"></div>' + ledger + '<div style="height:16px"></div>' + spec([
            "FR-P-07 与回测共用撮合内核：TC-P-01 要求同参数逐日净值一致（1e-6）",
            "FR-P-03 余额只能由流水推导；改余额入口不存在",
            "TC-P-02 重复提交 → 409「已有进行中的运行，是否跳转查看？」",
            "UI-03 拒单/差异在侧栏徽标与订单页默认可见"])
    return page("paper.html", "模拟盘：持仓与订单", "账户、T+1 可售、拒单原因、只追加流水",
                body, actions='<button class="btn btn-sm">次日结算</button>', crumb="模拟盘 / 账户 acct-01")


def p_recon():
    diff = [round(random.Random(9).gauss(0.0, 0.35), 2) for _ in range(60)]
    diff[41] = 3.8
    diff[42] = -1.2
    series = [("diff_bp", "var(--chart-1)", False, diff)]
    chart = card("逐日轧差（阈值 ±1bp）",
                 '<div class="legend" style="margin-bottom:6px"><span><i style="background:var(--chart-1)"></i>实际−期望 (bp)</span>'
                 '<span class="mono-sm">参考线 ±1bp，超限点标红</span></div>'
                 + line_chart(series, height=180, bands=[(-1, 1, "var(--ok-600)")], yfmt="%0.1f")
                 + '<div class="hint">公式：expected = Σ持仓损益 + 现金利息 − 成本；actual = (cash_T+Σmv_T)−(cash_{T-1}+Σmv_{T-1})</div>',
                 right=tag("5 日累计 0.4bp ≤ 5bp", "ok"))
    tbl = card("差异明细与追溯",
               table(["交易日", "期望", "实际", "diff(bp)", "状态", "追溯"],
                     [["2026-11-20", "+4,312.00", "+4,312.00", '<span class="num">+0.03</span>', tag("ok", "ok"), "—"],
                      ["2026-11-19", "+2,145.00", "+2,151.30", '<span class="down num">+3.80</span>', tag("open", "err"),
                       '<button class="btn btn-sm">追溯链路</button>'],
                      ["2026-11-18", "+1,204.00", "+1,204.12", '<span class="num">+0.12</span>', tag("ok", "ok"), "—"],
                      ["2026-11-17", "-3,340.00", "-3,344.60", '<span class="up num">-1.22</span>', tag("traced", "warn"),
                       '<span class="mono-sm">已定位</span>']],
                     ["l", "r", "r", "r", "l", "l"],
                     note_text="页面不提供任何「手工调整」输入；唯一出口是重放验证。"))
    trace = card("追溯链路（2026-11-19，+3.80bp）",
                 rows_block([
                     dotrow("err", "步骤 1 · 逐单重放定位到订单 ord-8842（002xxx 卖 200 股）"),
                     dotrow("warn", "步骤 2 · 记账金额 9,840.00 与流水 9,841.24 相差 1.24 元"),
                     dotrow("warn", "步骤 3 · 根因=整手取整后零股卖出费用四舍五入位数不一致（Decimal 2 位 vs 6 位）"),
                     dotrow("ok", "步骤 4 · 结论：engine/cost.py 舍入顺序缺陷 → 已建缺陷 DEF-117（S1，资金类）"),
                     dotrow("idle", "步骤 5 · 未加「调整」流水抹平；修复后需重放该日验证（TC-P-05/06）"),
                 ]),
                 right='<button class="btn btn-sm btn-primary">建缺陷并阻断发布</button>')
    body = chart + '<div style="height:16px"></div>' + '<div class="grid g-2-1">' + tbl + trace + "</div>" \
        + '<div style="height:16px"></div>' + card("重放验证（新副本，不污染原账本）",
                 '<div class="row" style="gap:8px;flex-wrap:wrap">'
                 + field("起始日", '<input class="input" value="2026-11-19">')
                 + field("账户", '<select class="input"><option>acct-01（原始）</option></select>')
                 + '<button class="btn btn-primary" style="margin-top:18px">生成重放副本</button></div>'
                 + '<div class="hint">影响：生成 acct-01-replay-20261120T2015；原账本前后 digest 相同（0 写入）。'
                 '需二次确认（TC-P-09）</div>', "危险操作页见 paper-replay.html") \
        + '<div style="height:16px"></div>' + spec([
            "FR-P-05 |diff_bp| > 1 必须写 recon_diff 并逐单追到底",
            "G-03 红线：连续 5 交易日轧差 ≤ 1bp/日、累计 ≤ 5bp",
            "TC-P-06 禁止调整流水抹平；G-03 断言不存在无来源 adjust 流水",
            "UI-03 未确认差异计入侧栏徽标（1），并出现在总览待办"])
    return page("paper-recon.html", "对账与差异追溯", "逐日轧差、差异定位链路与重放验证",
                body, crumb="模拟盘 / 对账")


def p_risk():
    rules = card("规则（role:risk 可编辑）",
                 table(["规则", "指标", "比较", "阈值", "动作", "优先级", "启用", "版本"],
                       [["R-DRAWDOWN-01 水位期回撤", "portfolio.max_drawdown_since_arbitration", "&gt;", "0.20",
                         tag("BLOCK_BUY", "err"), "10", '<span class="dot dot-ok"></span>', "v4"],
                        ["R-WEIGHT-01 单票权重", "position.weight", "&gt;", "0.10", tag("REJECT_ORDER", "warn"), "20",
                         '<span class="dot dot-ok"></span>', "v2"],
                        ["R-INDUSTRY-01 行业偏离", "industry.active_deviation", "&gt;", "0.08", tag("REDUCE", "warn"), "30",
                         '<span class="dot dot-ok"></span>', "v1"],
                        ["R-TURNOVER-01 日换手", "portfolio.turnover_daily", "&gt;", "0.60", tag("REJECT_ORDER", "warn"), "40",
                         '<span class="dot dot-ok"></span>', "v3"],
                        ["R-BLACKLIST-01 黑名单", "symbol.in_blacklist", "in", "12 项", tag("REJECT_ORDER", "warn"), "5",
                         '<span class="dot dot-ok"></span>', "v7"],
                        ["R-NEWLISTING-01 次新/ST", "instrument.age_days_lt_or_st", "&lt;", "60 日", tag("REJECT_ORDER", "warn"), "50",
                         '<span class="dot dot-idle"></span>', "v1"]],
                       ["l", "l", "l", "r", "l", "r", "l", "l"],
                       note_text="内置规则可停用不可删除；每次保存弹原因并记录前后值 diff（TC-R-09）。"
                                 "viewer/researcher/pm 均无编辑入口。"))
    events = card("风控事件（open 3）",
                  table(["交易日", "账户", "规则", "指标值", "动作", "状态", "操作人", "操作"],
                        [["2026-11-20", "acct-01", "R-WEIGHT-01", "10.42%", "REJECT_ORDER", tag("open", "err"), "—",
                          '<button class="btn btn-sm btn-primary">确认</button>'],
                         ["2026-11-19", "acct-01", "R-TURNOVER-01", "62.4%", "REJECT_ORDER", tag("open", "err"), "—",
                          '<button class="btn btn-sm btn-primary">确认</button>'],
                         ["2026-11-18", "acct-01", "R-BLACKLIST-01", "600xxx", "REJECT_ORDER", tag("open", "err"), "—",
                          '<button class="btn btn-sm">查看快照</button>'],
                         ["2026-11-12", "acct-01", "R-DRAWDOWN-01", "19.8%", "ALERT", tag("acked"), "王风控", "—"]],
                        ["l", "l", "l", "r", "l", "l", "l", "l"], pager_total=204,
                        note_text="确认（ack）必须带原因与操作人；仅 role:risk（TC-R-07）。"))
    body = rules + '<div style="height:16px"></div>' + events + '<div style="height:16px"></div>' \
        + card("事件详情抽屉（R-WEIGHT-01 预览）",
               '<div class="grid g2"><div>' + rows_block([
                   row("触发时点", "2026-11-20 20:02（post_trade）"),
                   row("标的", "600519 贵州茅台"),
                   row("指标值", "10.42% > 10.00%"),
                   row("动作", "订单拒单 + risk_event(open)"),
                   row("规则快照", "threshold=0.10, version=v2, scope=account:*"),
                   row("trace_id", "c91ad77e")]) + '</div><div><div class="card-h"><h2>触发时净值片段</h2></div>' \
               + area_line(dd(T0)[-40:], height=110) + "</div></div>", "触发上下文不可变") \
        + '<div style="height:16px"></div>' + spec([
            "FR-R-05 判定在服务端；绕过 UI 直调下单 API 仍被拒（TC-R-08，G-06）",
            "FR-R-03 BLOCK_BUY 只拒新增买入，不强平已有持仓",
            "TC-R-10 多规则同时命中：取最高优先级动作，全部记录",
            "侧栏徽标 3 = risk_event(open) 数，与本页一致"])
    return page("risk.html", "风控规则与事件", "阈值、动作、优先级、事件确认与不可变快照",
                body, actions='<button class="btn btn-sm">新增规则</button>', crumb="风控 / 规则与事件")


def p_breaker():
    banner = ('<div class="banner banner-err"><b>熔断进行中</b>'
              '<span>2026-11-12 触发 R-DRAWDOWN-01（水位期回撤 20.1% &gt; 20%）</span>'
              '<span class="tag tag-err">BLOCK_BUY</span>'
              '<span class="mono-sm">影响：仅拒绝新增买入，不强平已有持仓（FR-R-03）</span></div>')
    gauge = card("回撤水位",
                 '<div class="progress"><i style="width:100%;background:var(--err-600)"></i></div>'
                 + rows_block([
                     row("水位期内峰值回撤", "-20.10%"),
                     row("当前回撤", "-15.42%"),
                     row("解除条件", "回撤修复至 12% 以内且无新增 open 事件"),
                     row("持续天数", "6 交易日"),
                 ]))
    denied = card("熔断期间被拒订单",
                  table(["交易日", "标的", "方向", "委托", "原因码", "留痕"],
                        [["2026-11-20", "002594 比亚迪", "买", "31,000", "RISK_REJECT", '<span class="mono-sm">ord-9911 · CircuitBreakActive</span>'],
                         ["2026-11-19", "601899 紫金矿业", "买", "12,000", "RISK_REJECT", '<span class="mono-sm">ord-9874</span>'],
                         ["2026-11-13", "300750 宁德时代", "买", "4,000", "RISK_REJECT", '<span class="mono-sm">ord-9802</span>']],
                        ["l", "l", "l", "r", "l", "l"],
                        note_text="业务失败必须留 FAILED 痕，不静默成功（G-06 / TC-R-06）。"))
    release = ('<div class="card"><div class="card-h"><h2>解除熔断</h2><span class="sub">仅 role:risk</span></div>'
               + rows_block([
                   '<div class="row"><span class="k">当前角色</span><span class="tag">researcher</span>'
                   '<span class="mono-sm">无权限：入口对 researcher 显示为禁用并说明所需角色</span></div>'
                   + field("解除理由（必填）", '<input class="input" placeholder="复核结论 + 依据 run_id">')
                   + field("复核结论", '<select class="input"><option>回撤已修复，风控水位复核通过</option>'
                           '<option>误触发（数据缺陷）</option></select>')
                   + '<button class="btn btn-danger" disabled title="需要 role:risk">确认解除</button>'
               ])
               + '<div class="hint">解除后写 audit（actor/before/after）并在 24h 内在通知中心保留横幅</div></div>')
    body = banner + '<div class="grid g2">' + gauge + denied + "</div>" + '<div style="height:16px"></div>' + release \
        + '<div style="height:16px"></div>' + spec([
            "FR-R-04 事件须人工确认，解除需 role:risk 且原因必填（TC-R-07）",
            "UI-05 全页红顶条 + 只读锁：模拟盘买入按钮同步禁用（后端状态驱动）",
            "TC-R-01 熔断只拒新增买入，不强平",
            "FR-R-05 通过 API 直接下单同样被服务端拒（TC-R-08）"])
    return page("risk-breaker.html", "熔断状态", "触发依据、水位进度、被拒订单与解除面板",
                body, crumb="风控 / 熔断")


def p_jobs():
    rows = [
        ["fetch_bars_daily", "2026-11-20", tag("SUCCESS", "ok"), "5,312", "3m21s", "1", "—"],
        ["fetch_adj_factors", "2026-11-20", tag("SUCCESS", "ok"), "5,312", "8m04s", "1", "—"],
        ["fetch_fundamentals", "2026-11-20", tag("PARTIAL", "warn"), "1,204 / 5,312", "12m00s", "3",
         '<span class="mono-sm">QUANT-D-003 源限流</span>'],
        ["quality_check", "2026-11-20", tag("FAILED", "err"), "—", "0m48s", "3",
         '<span class="mono-sm">QUANT-O-001 store unavailable</span>'],
        ["factor_compute", "2026-11-20", tag("SUCCESS", "ok"), "63,744", "9m02s", "1", "—"],
        ["signal_generate", "2026-11-20", tag("SUCCESS", "ok"), "30", "0m12s", "1", "—"],
        ["paper_settle", "2026-11-20", tag("SKIPPED_UPSTREAM", ""), "—", "—", "0",
         '<span class="mono-sm">依赖 quality_check</span>'],
        ["reconcile", "2026-11-20", tag("SKIPPED_UPSTREAM", ""), "—", "—", "0", '<span class="mono-sm">级联跳过</span>'],
    ]
    tbl = table(["作业", "交易日", "状态", "行数", "耗时", "attempt", "错误 / 级联"], rows,
                ["l", "l", "l", "r", "r", "r", "l"],
                note_text="上游 PARTIAL 时下游默认 SKIPPED_UPSTREAM（TC-O-02）；"
                          "force 需 role:data 并在 job_run 标注。并发锁：同 job_id+trade_date 单实例。")
    timeline = card("attempt 时间线与断点续传",
                   rows_block([
                       dotrow("err", "attempt 1 · 09:12 · 超时 5,431 只中缺 217（QUANT-D-003）"),
                       dotrow("warn", "attempt 2 · 09:40 · 续传仅补缺口 217 → 缺 44（退避 2.4s）"),
                       dotrow("ok", "attempt 3 · 10:05 · 补齐 44，最终行数与全量一致（TC-D-11）"),
                   ])
                   + '<div class="hint">峰值限流 5 req/s；连续失败 3 次告警一次（TC-O-03/04）</div>')
    body = ('<div class="filters">' + selects("状态", ["全部", "SUCCESS", "PARTIAL", "FAILED", "SKIPPED_UPSTREAM"])
            + '<div class="field"><label>交易日</label><input class="input" value="2026-11-20"></div>'
            + '<button class="btn btn-sm">重跑失败</button><span class="top-spacer"></span>'
            + '<button class="btn btn-sm btn-primary">触发补数（role:data）</button></div>'
            + card("作业与水位", tbl, "近 1 交易日 11 个作业") + '<div style="height:16px"></div>' + timeline
            + '<div style="height:16px"></div>' + states_mock() + '<div style="height:16px"></div>' + spec([
                "FR-O-02 幂等键 (job_id, trade_date, attempt_bucket)，重跑不重复入库",
                "UI-04 长任务离开页面后进度常驻右上角（TC-X-10）",
                "TC-O-05 无 Docker 时顶部显示 DuckDB 降级徽标，全流程仍可用",
                "TC-O-08 密钥缺失/权限异常时启动明确报错并给期望路径"]))
    return page("data-jobs.html", "作业与数据水位", "调度、重试、幂等、级联跳过与断点续传",
                body, crumb="数据 / 作业")


def simple(fname, title, sub, blocks, crumb="", actions=""):
    body = ""
    for b in blocks:
        body += b + '<div style="height:16px"></div>'
    return page(fname, title, sub, body, actions=actions, crumb=crumb or ("量化研究 / " + title))


def p_amendments():
    return simple("data-amendments.html", "数据修正留痕", "只追加流水，原行保留，关联产物标 stale", [
        card("修正记录（41 条）", table(
            ["时间", "交易日", "标的", "字段", "原值", "新值", "理由", "操作人", "stale 影响"],
            [["2026-11-18 20:12", "2026-11-15", "600xxx", "close", "12.34", "13.24", "源端字段错位，按同花顺修正", "hegan",
              '<a href="backtest-runs.html">3 个 run</a>'],
             ["2026-11-11 09:40", "2026-11-10", "002xxx", "volume", "0", "1,234,500", "抓取空值补录", "hegan", "—"]],
            ["l", "l", "l", "l", "r", "r", "l", "l", "l"],
            note_text="「新增修正」对话框要求理由必填；无任何直接编辑行情入口（TC-D-09 / ADR-013）。")),
        card("新增修正（对话框预览）", modal_mock(
            "新增数据修正",
            [row("目标", "2026-11-15 · 600xxx · close"),
             row("原值 / 新值", "12.34 → 13.24"),
             row("理由（必填）", "源端字段错位，同花顺双源比对佐证"),
             row("影响范围", "12 个 factor_value 分区、3 个 backtest_run 将标 stale"),
             row("不可逆提示", "原行保留，下游需重算；不会自动改写历史结果")],
            cta="提交修正", danger=True)),
        spec(["FR-D-08 修正必须留痕（原值/新值/理由/操作人/时间）",
              "TC-D-09 断言原行未被 UPDATE；关联 run 标 stale",
              "ADR-013 数据只追加，查询时合并修正"]),
    ], crumb="数据 / 修正留痕")


def p_sources():
    rows = [["2026-11-20", "600519", "close", "1,680.00", "1,680.00", '<span class="num">0.0000%</span>', tag("一致", "ok")],
            ["2026-11-20", "000001", "close", "11.24", "11.24", '<span class="num">0.0000%</span>', tag("一致", "ok")],
            ["2026-11-19", "600xxx", "close", "12.34", "13.24", '<span class="down num">6.7700%</span>', tag("超阈值", "err")],
            ["2026-11-19", "300xxx", "amount", "5.21 亿", "5.19 亿", '<span class="num">0.3854%</span>', tag("超阈值", "err")]]
    return simple("data-sources.html", "双源比对", "东财（主源）与同花顺（校验源）字段级对照", [
        '<div class="grid g4">' + kpi("比对样本", "100 只 × 20 日", None, "TC-D-08 每日抽样") \
        + kpi("收盘价差异率", "0.008%", None, "阈值 0.01%") \
        + kpi("超阈值行", '<span class="down">2</span>', None, "逐条列出，不聚合掩盖") \
        + kpi("主源限流", "5 req/s", None, "抖动退避") + "</div>",
        card("差异明细", table(["交易日", "标的", "字段", "东财", "同花顺", "差异", "判定"], rows,
                              ["l", "l", "l", "r", "r", "r", "l"],
                              note_text="主源选择规则：东财为准，同花顺用于交叉验证；差异不自动改写行情，"
                                        "需走 data-amendments 留痕流程。")),
        spec(["FR-D-07 异常写入 data_issue 并可阻断", "TC-D-08 差异率 < 0.01%，超阈值逐条列出",
              "R-01 源改版/封禁时显式标记缺口，禁止静默填充"]),
    ], crumb="数据 / 双源比对")


def p_strategies():
    return simple("research-strategies.html", "策略与版本", "版本链、参数 diff、最近回测与体检结论", [
        card("策略列表", table(
            ["策略", "版本", "调仓", "最近回测", "OOS Sharpe", "体检", "门禁", "操作"],
            [["s2_multifactor 多因子月度", "v1", "月度", '<a href="backtest.html">run-a83f</a>', "0.71",
              tag("需确认", "warn"), tag("FAIL", "err"), '<button class="btn btn-sm">复制参数</button>'],
             ["s1_trend 沪深300 双均线", "v3", "日度", "run-77c2", "0.34", tag("pass", "ok"), tag("pass", "ok"),
              '<button class="btn btn-sm">复制参数</button>'],
             ["s3_rotation 行业轮动", "v2", "月度", "run-5e11", "-0.12", tag("FAIL", "err"), tag("pass", "ok"),
              '<button class="btn btn-sm">查看失败项</button>']],
            ["l", "l", "l", "l", "r", "l", "l", "l"])),
        card("版本对比（v1 vs v2 参数与指标 diff）", table(
            ["字段", "v1", "v2", "Δ"],
            [["Top N", "30", "40", "+10"], ["mom 权重", "0.25", "0.20", "-0.05"],
             ["换手上限", "60%", "45%", "-15pp"], ["OOS Sharpe", "0.71", "0.66", "-0.05"],
             ["cost 年化", "34.1%", "27.3%", "-6.8pp"]],
            ["l", "r", "r", "r"], note_text="code_digest 与 config_hash 同时展示，保证可复现（TC-B-15）。")),
        spec(["FR-S-03 参数 + 代码摘要 + 数据版本三者绑定",
              "FR-A-04 体检 FAIL 的策略不得进入信号发布（列表标红）",
              "UI-08 版本管理必须有界面入口，不得只靠 CLI"]),
    ], crumb="研究 / 策略与版本")


def p_ai_lab():
    chat = card("会话（FR-A-01 口径澄清）",
               rows_block([
                   '<div class="row"><span class="tag">你</span><span>想加一个「缩量回调」因子：放量上涨后缩量回踩不破 20 日线</span></div>',
                   '<div class="row"><span class="tag tag-info">系统</span><span>口径确认 3 项：①「放量」阈值取近 20 日均量的 1.5 倍？'
                   '②「缩量」是否用当日量 < 前日量 × 0.6？③「不破 20 日线」用收盘价还是最低价？（缺失定义必须先问，TC-A-07）</span></div>',
                   '<div class="row"><span class="tag">你</span><span>①是 ②是 ③用收盘价，且停牌日跳过</span></div>',
                   '<div class="row"><span class="tag tag-info">系统</span><span>已生成草稿 + 静态检查结果，见右栏。'
                   '声明：模型不产出下单金额与风控阈值（FR-A-05）</span></div>']))
    code = card("代码草稿与静态检查",
                '<pre class="mono-sm" style="margin:0;white-space:pre-wrap;background:var(--bg-1);'
                'padding:12px;border-radius:var(--r-sm);line-height:1.6">'
                'def compute(ctx):\n'
                '    vol = ctx.bars("volume", 20)            # 仅 ≤ T，物理隔离\n'
                '    ma20 = ctx.bars("adj_close", 20).rolling(20, min_periods=20).mean()\n'
                '    pulse = vol.iloc[-1] > 1.5 * vol.mean()\n'
                '    shrink = (vol.iloc[-1] < vol.iloc[-2] * 0.6) & ~vol.isna()\n'
                '    hold = ctx.bars("adj_close", 1).iloc[-1] >= ma20.iloc[-1]\n'
                '    return where(pulse & shrink & hold, 1.0, nan)</pre>'
                + '<div class="checks" style="margin-top:10px">'
                + '<div class="check pass"><span class="n">未来切片访问</span><span class="mono-sm">未发现越界读取</span>'
                  '<span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
                + '<div class="check fail"><span class="n">import 白名单</span>'
                  '<span class="mono-sm">第 1 行曾用 talib（不在白名单）</span><span class="top-spacer"></span>'
                  + tag("已拒绝", "err") + "</div>"
                + '<div class="check pass"><span class="n">NaN / 极值</span><span class="mono-sm">NaN 率 61%（阈值 80%）</span>'
                  '<span class="top-spacer"></span>' + tag("pass", "ok") + "</div>"
                + '<div class="check warn"><span class="n">相关性</span><span class="mono-sm">与 rev_5 = 0.71（&lt; 0.95）</span>'
                  '<span class="top-spacer"></span>' + tag("OK", "warn") + "</div></div>")
    run = card("沙箱运行与体检表",
               rows_block([
                   dotrow("ok", "沙箱：pandas/numpy 白名单 · RLIMIT_AS 4GB · 墙钟 180s · 禁网禁写（TC-A-02）"),
                   dotrow("ok", "输出 6,312,408 行 ≤ 上限 2,000,000/日截面（TC-A-09）"),
                   dotrow("err", "样本外 Sharpe = -0.21（红线：OOS ≥ 0.3）"),
                   dotrow("err", "成本占毛收益 = 52.3%（红线 ≤ 40%）"),
                   dotrow("warn", "参数扰动 ±20%：Sharpe 区间 [-0.31, 0.04] 符号翻转"),
               ])
               + '<div style="display:flex;gap:8px;margin-top:10px;align-items:center">'
               + '<button class="btn btn-primary" disabled title="体检 FAIL：命中 2 条红线">注册为因子</button>'
               + '<span class="tag tag-err">ChecklistFail (QUANT-A-002)</span>'
               + '<span class="mono-sm">结论：不进入发布与模拟盘；可改口径重跑，禁止放宽阈值凑绿</span></div>',
               "红线判定=引擎输出，前端不重算")
    body = ('<div class="grid g-2-1">' + chat + run + "</div>" + '<div style="height:16px"></div>' + code
            + '<div style="height:16px"></div>' + spec([
                "FR-A-02 沙箱：白名单 import、RLIMIT、墙钟、禁网禁写、崩溃不影响 api/worker",
                "FR-A-05 LLM 不参与资金决策：页面无任何下单金额/阈值控件",
                "TC-A-05 过拟合样例必须 ChecklistFail 并锁注册",
                "P3 交付；P1/P2 阶段该页为原型，不标运行态"])
            )
    return page("research-ai-lab.html", "AI 研究台", "需求澄清、代码草稿、沙箱执行与过拟合体检",
                body, actions='<button class="btn btn-sm">新会话</button>', crumb="研究 / AI 研究台")


def p_runs():
    rows = [["run-a83f", "s2_multifactor v1", "2016-01-04 → 2025-12-31", tag("FAILED 门禁", "err"), "0.71", "-18.06%",
             "8f3c2a1d", '<a class="btn btn-sm" href="backtest.html">详情</a>'],
            ["run-77c2", "s1_trend v3", "2016 → 2025", tag("pass", "ok"), "0.34", "-22.10%", "b19e77c0",
             '<a class="btn btn-sm">详情</a>'],
            ["run-5e11", "s3_rotation v2", "2016 → 2025", tag("体检 FAIL", "err"), "-0.12", "-31.40%", "44d0c9aa",
             '<a class="btn btn-sm">失败项</a>'],
            ["run-2b90", "s2_multifactor v1", "2022 → 2025", tag("succeeded", "ok"), "0.66", "-16.22%", "9ac31f02",
             '<a class="btn btn-sm">详情</a>'],
            ["run-0c44", "s2_multifactor v1", "2016 → 2021", tag("running 64%", "warn"), "—", "—", "—",
             '<button class="btn btn-sm">取消</button>']]
    body = ('<div class="filters">' + selects("策略", ["全部", "s2_multifactor", "s1_trend", "s3_rotation"])
            + seg("门禁", ["全部", "pass", "FAIL"]) + '<button class="btn btn-sm">只看 OOS</button>'
            + '<span class="top-spacer"></span><a class="btn btn-sm btn-primary" href="backtest.html">发起回测</a></div>'
            + card("回测记录", table(["run_id", "策略/版本", "区间", "状态", "OOS Sharpe", "最大回撤", "config_hash", "操作"],
                                    rows, ["l", "l", "l", "l", "r", "r", "l", "l"], pager_total=86,
                                    note_text="config_hash 点击进入同 hash 重放，结果必须逐值一致（TC-B-15）。"))
            + '<div style="height:16px"></div>' + spec([
                "FR-B-12 可复现：hash = 参数+代码摘要+数据版本+seed",
                "STALE 标记（数据修正后）在状态列显示为 tag-warn",
                "P1 运行态：CLI `quant backtest` + HTML 报告；页面为 P2 联调对象"])
            )
    return page("backtest-runs.html", "回测记录", "历史运行、状态、config_hash 与可复现入口", body,
                crumb="回测 / 记录")


def p_signals_history():
    rows = [["2026-10-20", "sig-1020-01", tag("published", "info"), "41.9%", "李经理", "10-20 20:02",
             '<button class="btn btn-sm">撤回</button>'],
            ["2026-09-20", "sig-0920-02", tag("superseded"), "36.4%", "李经理", "09-20 20:04", "—"],
            ["2026-09-18", "sig-0918-01", tag("withdrawn", "err"), "35.1%", "李经理", "09-18 14:22",
             '<span class="mono-sm">原因：数据修正后 stale</span>'],
            ["2026-08-20", "sig-0820-01", tag("published", "info"), "44.2%", "李经理", "08-20 20:01", "—"]]
    body = card("发布历史", table(["交易日", "run_id", "状态", "换手", "操作人", "发布时间", "操作"], rows,
                                  ["l", "l", "l", "r", "l", "l", "l"], pager_total=48,
                                  note_text="状态机：draft → published → superseded/withdrawn；"
                                            "已发布内容不可修改（TC-G-02）。撤回必须带原因。")) \
        + '<div style="height:16px"></div>' + card("信号 → 实际成交偏差（FR-G-06）",
        table(["交易日", "标的", "目标权重", "实际权重", "Δ", "原因"],
              [["2026-10-20", "002594", "5.20%", "4.10%", '<span class="down num">-1.10%▼</span>', "开盘一字涨停部分成交"],
               ["2026-10-20", "601398", "-1.90%", "-1.90%", '<span class="num">0.00%</span>', "全额成交"]],
              ["l", "l", "r", "r", "r", "l"])) + '<div style="height:16px"></div>' + spec([
        "FR-G-05 通知开关与内容在系统设置控制（P2）", "TC-G-03 撤回带原因与操作人"])
    return page("signals-history.html", "历史信号", "状态机、撤回原因与实际成交偏差", body, crumb="信号 / 历史")


def p_replay():
    body = ('<div class="banner banner-err"><b>危险操作</b><span>重放将创建独立账户副本；原账本执行 0 写入（FR-P-06）。'
            '若目标区间存在未确认对账差异，重放结果不可用于结论。</span></div>'
            + '<div class="grid g2">'
            + card("参数", '<div class="grid">' + field("账户", '<select class="input"><option>acct-01</option></select>')
                   + field("起始日", '<input class="input" value="2026-11-17">')
                   + field("副本命名", '<input class="input" value="acct-01-replay-20261120T2015">')
                   + field("成本模型", '<select class="input"><option>与原始一致（推荐，用于验证）</option>'
                           '<option>覆盖为 10bp 滑点</option></select>')
                   + '<button class="btn btn-danger">生成重放副本</button></div>')
            + card("影响与证明", rows_block([
                dotrow("ok", "原账本 digest（前）= 3f9a…c21 预计不变"),
                dotrow("idle", "新副本 digest = （运行后给出）"),
                dotrow("warn", "重放期间不触发风控事件，不进入总览待办"),
                dotrow("idle", "完成后仅在 /paper/replay 列表可见"),
            ]) + '<div class="hint">验收要求：重放后对原账本前后 digest 比对，必须相同（TC-P-09）</div>')
            + "</div>" + '<div style="height:16px"></div>' + modal_mock(
                "确认重放账本",
                [row("账户 / 起始日", "acct-01 · 2026-11-17"),
                 row("副本", "acct-01-replay-20261120T2015"),
                 row("原账本影响", "0 写入（digest 前后比对通过后才算成功）"),
                 row("成本", "预计 3 交易日结算 + 对账，约 40s")],
                cta="确认生成副本", danger=True)
            + '<div style="height:16px"></div>' + spec([
                "G-03 红线不因重放而放宽：重放副本同样逐日轧差 ≤ 1bp",
                "数据保护规则：不覆盖、不下线原账本",
                "TC-P-09 断言原账本零写入"])
            )
    return page("paper-replay.html", "账本重放", "独立副本验证，不污染原账本", body, crumb="模拟盘 / 重放")


def p_system_config():
    rows = [["RF_ANNUAL", "0.015", "无风险利率（年化）", "影响 Sharpe/Sortino", "标黄历史 run 口径差异"],
            ["COST_SLIPPAGE_BP", "5", "默认滑点 bp", "影响所有回测/模拟盘", "同上"],
            ["REBALANCE", "monthly", "调仓频率", "影响换手与成本", "新 run 生效"],
            ["UNIVERSE", "ALL_A", "样本池", "影响首导入耗时", "重跑数据"],
            ["STORE_MODE", "auto（Timescale→DuckDB）", "存储模式", "当前=Timescale", "重启生效"],
            ["FETCH_RATE_LIMIT", "5 req/s", "抓取限流", "影响导入时长", "即时"],
            ["MAX_DD_BLOCK", "0.20", "熔断回撤阈值", "风控行为", "需 role:risk"],
            ["AUTH_TOKEN_SECRET", '<span class="mono-sm">~/.config/quant-pro/ 600 ✓</span>', "令牌密钥", "不回显值", "—"]]
    body = card("参数与口径", table(["key", "值", "含义", "影响面", "生效条件"], rows,
                                    ["l", "l", "l", "l", "l"],
                                    note_text="密钥类只显路径与权限位，永不回显值（TC-X/G-09）；"
                                              "改口径项提交前显示「历史 run 口径差异」提示并写审计。")) \
        + '<div style="height:16px"></div>' + card("环境与依赖自检", rows_block([
            dotrow("ok", "Python 3.12.6（/Users/hegan/.local/bin/python3.12）"),
            dotrow("warn", "系统 Python 3.9.6 不满足依赖，bootstrap 已显式选择 3.12（TC-O-06）"),
            dotrow("ok", "Docker 可用 · quant-timescale :5433 healthy"),
            dotrow("ok", "东财 push2 200 · 同花顺 200 · pypi 200"),
            dotrow("warn", "TUSHARE_TOKEN 未配置 → 财务走免费源，PIT 精度降级并显式声明"),
        ])) + '<div style="height:16px"></div>' + spec([
            "UI-DESIGN §12：配置必须有管理台入口，不得只靠 yaml/CLI",
            "A-02 数据源 token 缺失时页面标黄，报告中同样标注（R-02）"])
    return page("system-config.html", "参数与口径配置", "口径类只读展示 + 可配项编辑（带影响提示）", body,
                crumb="系统 / 参数与口径")


def p_system_audit():
    rows = [["2026-11-20 20:02", "王风控", "risk.event.ack", "evt-3321", "status open → acked", "回撤复核通过", "✓ 留痕"],
            ["2026-11-20 19:46", "张研究员", "signal.create", "sig-20261120-01", "— → draft", "月度调仓", "✓"],
            ["2026-11-19 09:12", "hegan", "data.amend", "bar#600xxx", "12.34 → 13.24", "双源比对佐证", "✓"],
            ["2026-11-18 21:40", "system", "job.retry", "fetch_fundamentals", "attempt 2", "源限流退避", "✓"]]
    body = card("审计日志", table(["时间", "操作人", "动作", "对象", "before → after", "原因", "留痕"], rows,
                                  ["l", "l", "l", "l", "l", "l", "l"], pager_total=3921,
                                  note_text="筛选：actor / action / 对象 / 时间；写操作成功即返回记录 ID，"
                                            "页面显示「已留痕 #id」（UI §8 审计约定）。")) \
        + '<div style="height:16px"></div>' + states_mock() + '<div style="height:16px"></div>' \
        + spec(["TC-R-09 规则阈值变更前后值入 app_config 审计",
                "FR-R-04 事件确认必须带操作人 + 原因",
                "G-09 审计页不得出现口令/token 值（TC-S-05）"])
    return page("system-audit.html", "审计日志", "写操作全量留痕与检索", body, crumb="系统 / 审计")


def build():
    os.makedirs(PAGES, exist_ok=True)
    os.makedirs(ASSETS, exist_ok=True)
    with open(os.path.join(ASSETS, "tokens.css"), "w", encoding="utf-8") as f:
        f.write(TOKENS_CSS)
    with open(os.path.join(ASSETS, "app.css"), "w", encoding="utf-8") as f:
        f.write(APP_CSS)
    out = [
        p_index(), p_dashboard(),
        p_data_quality(), p_amendments(), p_sources(), p_jobs(),
        p_research_factors(), p_strategies(), p_ai_lab(),
        p_backtest(), p_runs(),
        p_signals(), p_signals_history(),
        p_paper(), p_recon(), p_replay(),
        p_risk(), p_breaker(),
        p_system_config(), p_system_audit(),
    ]
    for fname, html in out:
        with open(os.path.join(PAGES, fname), "w", encoding="utf-8") as f:
            f.write(html)
    print("生成 %d 页 → prototype/pages/" % len(out))
    return [f for f, _ in out]


if __name__ == "__main__":
    import re

    def data_cells(text):
        """脏值规则只作用于「渲染出来的数据」：表格单元格与 KPI 数值，不含技术标签与规格注释。"""
        cells = re.findall(r"<td[^>]*>(.*?)</td>", text, re.S)
        cells += re.findall(r'<div class="value num">(.*?)</div>', text, re.S)
        return [c for c in cells if re.search(r"\bNaN\b|\bnan\b|undefined|\bnull\b|None", c)]

    if "--check" in sys.argv:
        pages = build()
        bad = [(fname, cell) for fname in pages for cell in data_cells(
            open(os.path.join(PAGES, fname), encoding="utf-8").read())]
        print("脏值检查（TC-X-02）：%s" % ("通过" if not bad else bad[:5]))
        sys.exit(1 if bad else 0)
    build()
