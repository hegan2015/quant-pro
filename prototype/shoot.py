#!/usr/bin/env python3
"""用本机 Chrome 无头模式把 prototype/pages/*.html 截图到 prototype/shots/*.png。

用法：python3 prototype/shoot.py [页面名 ...]
默认截 1440 宽（设计基准），高度按页面内容指定。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "pages")
SHOTS = os.path.join(HERE, "shots")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SIZES = {
    "index.html": (1440, 1500),
    "dashboard.html": (1440, 1600),
    "research-factors.html": (1440, 1500),
    "backtest.html": (1440, 2300),
    "signals.html": (1440, 1800),
    "paper.html": (1440, 1500),
    "paper-recon.html": (1440, 1400),
    "risk.html": (1440, 1500),
    "risk-breaker.html": (1440, 1200),
    "data-quality.html": (1440, 1500),
    "data-jobs.html": (1440, 1500),
    "research-ai-lab.html": (1440, 1500),
}


def shoot(fname):
    w, h = SIZES.get(fname, (1440, 1400))
    out = os.path.join(SHOTS, fname.replace(".html", ".png"))
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--default-background-color=FFFFFFFF",
        "--window-size=%d,%d" % (w, h),
        "--screenshot=" + out,
        "file://" + os.path.join(PAGES, fname),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    ok = os.path.exists(out) and os.path.getsize(out) > 1000
    if not ok:
        print("FAIL", fname, r.stderr[-400:])
    return ok, out


def main(argv):
    os.makedirs(SHOTS, exist_ok=True)
    targets = argv or sorted(SIZES)
    done = []
    for f in targets:
        ok, path = shoot(f)
        if ok:
            done.append(path)
            print("shot %s (%.0f KB)" % (os.path.basename(path), os.path.getsize(path) / 1024))
    print("共 %d/%d 张成功" % (len(done), len(targets)))
    return 0 if len(done) == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main([a if a.endswith(".html") else a + ".html" for a in sys.argv[1:]]))
