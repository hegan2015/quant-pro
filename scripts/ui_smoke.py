#!/usr/bin/env python3
"""控制台浏览器实测（Playwright + Chromium）：登录 → 8 页 → 发布/结算/确认流。

用法：.venv/bin/python scripts/ui_smoke.py
前置：bash scripts/serve.sh 已启动 API(8102) 与控制台(8101)。
产物：data/reports/ui/*.png + 控制台日志无 error 断言。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "reports" / "ui"
OUT.mkdir(parents=True, exist_ok=True)

from playwright.sync_api import sync_playwright  # noqa: E402

TOKEN = next(iter(json.loads((Path.home() / ".config" / "quant-pro" / "auth.json")
                             .read_text())["tokens"]))
# 控制台与 API 同源（run.sh 起 :8102）；独立静态服务 8101 仍可用环境变量覆盖
BASE = os.environ.get("QP_CONSOLE", "http://127.0.0.1:8102")


def main() -> int:
    errors: list[str] = []
    shots: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/#/login")
        page.wait_for_selector("input[placeholder='qp-...']", timeout=15000)
        page.fill("input[placeholder='qp-...']", TOKEN)
        page.click("button:has-text('登录')")
        page.wait_for_selector(".qp-top", timeout=15000)
        # 断言总览真的渲染出净值图（曾经加载态被误显示为「尚无回测记录」）
        page.wait_for_selector("svg.chart", timeout=30000)
        assert "尚无回测记录" not in page.inner_text("main"), "总览把加载中空当成无数据"
        # 数据水位状态栏必须留在首屏视口内（曾用 calc(100vh - 108px) 魔数把它挤到折叠线以下）
        foot_box = page.locator("footer.qp-foot").bounding_box()
        vh = page.evaluate("window.innerHeight")
        assert foot_box and foot_box["y"] + foot_box["height"] <= vh + 1, (
            f"状态栏不在视口内：{foot_box} innerHeight={vh}")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "01-dashboard.png"))
        shots.append("01-dashboard")

        for key, name, wait in [
            ("data", "02-data", ".el-table"),
            ("research", "03-research", ".el-table"),
            ("backtest", "04-backtest", ".el-form"),
            ("signals", "05-signals", ".el-table"),
            ("paper", "06-paper", ".el-tabs"),
            ("risk", "07-risk", ".el-table"),
            ("system", "08-system", "pre"),
        ]:
            page.goto(BASE + "/#/" + key)
            page.wait_for_selector(wait, timeout=20000)
            page.wait_for_timeout(600)
            if key == "data":
                # 标的列必须解析出中文名（名称映射来自 /api/instruments/names，登录后取一次）
                cells = page.locator(".sym-cell").count()
                named = page.locator(".sym-cell .nm").count()
                assert cells > 0 and named == cells, f"标的列缺中文名：{named}/{cells}"
            page.screenshot(path=str(OUT / f"{name}.png"))
            shots.append(name)

        # 信号流：生成草稿 → 发布（勾选确认）→ 撤回
        page.goto(BASE + "/#/signals")
        page.wait_for_selector(".el-table", timeout=20000)
        page.click("button:has-text('生成当日信号')")
        dlg = page.locator(".el-dialog", has_text="生成信号草稿")
        dlg.wait_for(state="visible", timeout=10000)
        dlg.locator("button:has-text('生成')").click()
        page.wait_for_selector(".checks", timeout=60000)
        page.screenshot(path=str(OUT / "09-signal-draft.png"))
        shots.append("09-signal-draft")
        pub_btn = page.locator("button:has-text('发布')").first
        if pub_btn.is_visible():
            pub_btn.click()
            pdlg = page.locator(".el-dialog", has_text="发布信号")
            pdlg.wait_for(state="visible", timeout=10000)
            pdlg.locator(".el-checkbox").click()
            pdlg.locator("button:has-text('确认发布')").click()
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT / "10-signal-published.png"))
            shots.append("10-signal-published")

        # 模拟盘：新建账户 → 结算 → 对账页
        page.goto(BASE + "/#/paper")
        page.wait_for_selector(".el-tabs", timeout=20000)
        page.click("button:has-text('新建账户')")
        adlg = page.locator(".el-dialog", has_text="新建模拟盘账户")
        adlg.wait_for(state="visible", timeout=10000)
        adlg.locator("button:has-text('创建')").click()
        page.wait_for_timeout(1500)
        page.locator(".filters button:has-text('结算')").click()
        sdlg = page.locator(".el-dialog", has_text="结算到某日")
        sdlg.wait_for(state="visible", timeout=10000)
        sdlg.locator("button:has-text('结算')").click()
        page.wait_for_timeout(6000)
        page.click(".el-tabs__item:has-text('对账')")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "11-paper-recon.png"))
        shots.append("11-paper-recon")

        # 亮色主题：切换后必须仍渲染数据且无报错（主题不是装饰，两档都要可用）
        page.click("button[title^='切换主题']")
        page.wait_for_timeout(600)
        assert page.evaluate("document.documentElement.dataset.theme") == "light"
        page.goto(BASE + "/#/dashboard")
        page.wait_for_selector("svg.chart", timeout=30000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "12-dashboard-light.png"))
        shots.append("12-dashboard-light")
        page.click("button[title^='切换主题']")   # 还原默认暗色
        page.wait_for_timeout(400)

        browser.close()

    real_errors = [e for e in errors if "favicon" not in e.lower()]
    print("截图:", ", ".join(shots))
    print("控制台 error:", real_errors if real_errors else "无")
    ok = not real_errors and len(shots) >= 8
    print("UI 实测:", "通过" if ok else "未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
