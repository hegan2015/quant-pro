"""API 门禁用例（G-06 / TC-R-08 / TC-S-01..03）：鉴权、RBAC、发布流、模拟盘流。"""
from __future__ import annotations

import json
import os
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from core.config import settings
from tests.test_p2 import make_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = make_store(tmp_path)
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "p2.duckdb"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(settings, "SECRETS_DIR", cfg_dir)
    from app.api import auth
    monkeypatch.setattr(auth, "AUTH_FILE", cfg_dir / "auth.json")
    from app.api import main as api
    monkeypatch.setattr(api, "store", lambda: db)
    tok = auth.ensure_dev_token()
    c = TestClient(api.app)
    c.headers.update({"Authorization": f"Bearer {tok}"})
    return c, db, tok


def test_static_mount_does_not_shadow_api_routes(client):
    """回归防护：控制台静态资源挂在 "/"，若注册顺序在路由之前会把 /api 全部遮蔽成 404。

    曾因此导致信号 / 模拟盘 / 风控页「没有初始化数据」。
    """
    from app.api.main import app
    c, db, tok = client
    kinds = [getattr(r, "path", None) for r in app.routes]
    mount_idx = next(i for i, r in enumerate(app.routes)
                     if type(r).__name__ == "Mount")
    api_after = [r.path for r in app.routes[mount_idx + 1:] if getattr(r, "path", "").startswith("/api")]
    assert not api_after, f"这些 /api 路由定义在静态挂载之后，会被遮蔽：{api_after}"
    for path in ("/api/signals", "/api/paper/accounts", "/api/risk/rules",
                 "/api/risk/events", "/api/risk/breaker", "/api/factors"):
        assert c.get(path).status_code == 200, f"{path} 被静态挂载吞掉（404）"


def test_healthz_open_and_api_gated(client):
    c, db, tok = client
    assert c.get("/healthz").status_code == 200
    bare = TestClient(__import__("app.api.main", fromlist=["app"]).app)
    assert bare.get("/api/status").status_code == 401
    assert bare.get("/api/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_rbac_viewer_cannot_publish(client):
    c, db, tok = client
    from app.api import auth
    blob = json.loads(auth.AUTH_FILE.read_text())
    blob["tokens"][tok]["roles"] = ["viewer"]
    auth.AUTH_FILE.write_text(json.dumps(blob))
    days = db.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    r = c.post("/api/signals", json={"trade_date": str(days[-1]),
                                     "params": {"top_n": 10, "factors": {"mom_20": 1.0},
                                                "constraints": {"max_weight": .2,
                                                                "max_positions": 10,
                                                                "min_positions": 1}}})
    assert r.status_code == 403, "viewer 不得生成/发布信号"


def test_signal_publish_flow_over_http(client):
    c, db, tok = client
    days = db.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    r = c.post("/api/signals", json={"trade_date": str(days[-1]),
                                     "params": {"top_n": 10,
                                                "factors": {"mom_20": .5, "vol_60": .5},
                                                "constraints": {"max_weight": .2,
                                                                "max_positions": 10,
                                                                "min_positions": 1}}})
    assert r.status_code == 201, r.text
    rid = r.json()["run_id"]
    assert c.post(f"/api/signals/{rid}/publish", json={"confirm": False}).status_code == 422
    ok = c.post(f"/api/signals/{rid}/publish", json={"confirm": True})
    assert ok.status_code == 200 and ok.json()["status"] == "published"
    assert c.post(f"/api/signals/{rid}/withdraw", json={"reason": ""}).status_code == 422
    w = c.post(f"/api/signals/{rid}/withdraw", json={"reason": "stale"})
    assert w.json()["status"] == "withdrawn"


def test_paper_settle_and_reconcile_over_http(client):
    c, db, tok = client
    days = db.trade_days(date(2024, 1, 1), date(2024, 6, 30))
    r = c.post("/api/signals", json={"trade_date": str(days[10]),
                                     "params": {"top_n": 10,
                                                "factors": {"mom_20": .5, "vol_60": .5},
                                                "constraints": {"max_weight": .2,
                                                                "max_positions": 10,
                                                                "min_positions": 1}}})
    rid = r.json()["run_id"]
    c.post(f"/api/signals/{rid}/publish", json={"confirm": True})
    a = c.post("/api/paper/accounts", json={"name": "t", "start_date": str(days[0])})
    aid = a.json()["account_id"]
    s = c.post(f"/api/paper/accounts/{aid}/settle", json={"upto": str(days[40])})
    assert s.status_code == 200, s.text
    assert s.json()["recon_max_bp"] <= 1.0
    rec = c.get(f"/api/paper/accounts/{aid}/reconciliation").json()
    assert rec and all(abs(x["diff_bp"]) <= 1.0 for x in rec)
    rp = c.post(f"/api/paper/accounts/{aid}/replay", json={"from_date": str(days[20])})
    assert rp.status_code == 201 and rp.json()["account_id"] != aid


def test_risk_ack_requires_risk_role(client):
    c, db, tok = client
    from core.risk import engine as risk
    risk.evaluate(db, risk.Snapshot(trade_date=date(2024, 3, 1), portfolio_max_drawdown=0.3))
    ev = c.get("/api/risk/events", params={"status": "open"}).json()
    assert ev
    from app.api import auth
    blob = json.loads(auth.AUTH_FILE.read_text())
    blob["tokens"][tok]["roles"] = ["pm"]
    auth.AUTH_FILE.write_text(json.dumps(blob))
    assert c.post(f"/api/risk/events/{ev[0]['id']}/ack",
                  json={"reason": "x"}).status_code == 403
    blob["tokens"][tok]["roles"] = ["risk"]
    auth.AUTH_FILE.write_text(json.dumps(blob))
    ok = c.post(f"/api/risk/events/{ev[0]['id']}/ack", json={"reason": "复核通过"})
    assert ok.status_code == 200
    assert c.get("/api/risk/breaker").json()["open"] is False


def test_sql_injection_in_symbol_param(client):
    c, db, tok = client
    r = c.get("/api/bars", params={"start": "2024-01-01", "end": "2024-03-01",
                                   "symbol": "S000.SZ' OR '1'='1"})
    assert r.status_code == 200
    assert r.json() == [], "注入串必须被当作普通值，不得返回全表"
