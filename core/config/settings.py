"""配置、密钥外置与可复现哈希（FR-B-12 / AP-06 / 密钥仓库外纪律）。

密钥只从 `~/.config/quant-pro/`（600）或环境变量读取，仓库内只保留 example；
任何口令不得拼入命令行参数（异常 traceback 会回显）。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
REPORT_DIR = DATA_DIR / "reports"
LOG_DIR = DATA_DIR / "logs"
SECRETS_DIR = Path(os.environ.get("QUANT_CONFIG_DIR", Path.home() / ".config" / "quant-pro"))

DEFAULTS = {
    "STORE_MODE": "auto",
    "DB_PATH": str(DATA_DIR / "mkt.duckdb"),
    "UNIVERSE": "LIQUID_1000",
    "UNIVERSE_SIZE": 1000,
    "START_DATE": "2016-01-04",
    "END_DATE": "2025-12-31",
    "TRAIN_END": "2021-12-31",
    "REBALANCE": "monthly",
    "RF_ANNUAL": 0.015,
    "BENCHMARK": "000300",
    "INITIAL_CAPITAL": 1_000_000.0,
    "FETCH_RATE_LIMIT": 6.0,
    "FETCH_CONCURRENCY": 8,
    "COST": {"commission_bp": 2.5, "min_commission": 5.0, "stamp_tax_sell_bp": 5.0,
             "transfer_bp": 0.1, "slippage_bp": 5.0},
    "CONSTRAINTS": {"max_weight": 0.10, "max_positions": 30, "min_positions": 10,
                    "min_cash": 0.0, "max_turnover": 0.60, "max_industry_dev": 0.08},
}
SECRET_KEYS = ("TUSHARE_TOKEN", "AUTH_TOKEN_SECRET", "PG_PASSWORD", "LLM_API_KEY")


@dataclass
class Settings:
    values: dict = field(default_factory=lambda: dict(DEFAULTS))
    secrets: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __getitem__(self, k):
        return self.values[k]

    get = __getitem__

    @property
    def cost(self) -> dict:
        return dict(self.values["COST"])

    @property
    def constraints(self) -> dict:
        return dict(self.values["CONSTRAINTS"])


def _read_secrets_file() -> dict:
    f = SECRETS_DIR / "settings.json"
    if not f.exists():
        return {}
    mode = f.stat().st_mode & 0o777
    if mode & 0o077:
        print(f"[warn] {f} 权限 {oct(mode)} 过宽，建议 chmod 600（G-09）")
    return json.loads(f.read_text(encoding="utf-8"))


def load(settings_path: str | None = None) -> Settings:
    vals = dict(DEFAULTS)
    warns: list[str] = []
    user_file = Path(settings_path) if settings_path else SECRETS_DIR / "settings.json"
    secrets: dict = {}
    if user_file.exists():
        blob = json.loads(user_file.read_text(encoding="utf-8"))
        secrets = {k: blob.pop(k) for k in list(blob) if k in SECRET_KEYS}
        vals.update(blob)
    for k in list(vals):
        env = os.environ.get(f"QUANT_{k}")
        if env is not None:
            vals[k] = type(vals[k])(env) if not isinstance(vals[k], (dict,)) else vals[k]
    for k in SECRET_KEYS:
        env = os.environ.get(k)
        if env:
            secrets[k] = env
    if not secrets.get("TUSHARE_TOKEN"):
        warns.append("TUSHARE_TOKEN 未配置：财务类因子不可用，PIT 精度降级（A-02 / R-02）")
    return Settings(values=vals, secrets=secrets, warnings=tuple(warns))


def code_digest() -> str:
    h = hashlib.sha256()
    for base in ("core", "app"):
        for path in sorted((ROOT / base).rglob("*.py")):
            h.update(str(path.relative_to(ROOT)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


def config_hash(cfg: dict, data_version: str, digest: str | None = None) -> str:
    """同哈希必须重跑出逐值一致的结果（TC-B-15）。"""
    payload = canonical({
        "cfg": cfg, "data_version": data_version, "code_digest": digest or code_digest(),
    })
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_benchmark_returns(store, code: str, start: date, end: date) -> pd.Series:
    rows = store.query(
        "SELECT ts, close FROM index_bar WHERE index_code = ? AND ts BETWEEN ? AND ?"
        " ORDER BY ts", [code, start, end])
    if not rows:
        raise RuntimeError(f"基准指数 {code} 在 {start}..{end} 无数据，拒绝用 0 收益代替")
    idx = [r[0].date() if isinstance(r[0], datetime) else r[0] for r in rows]
    s = pd.Series([float(r[1]) for r in rows], index=idx, dtype="float64")
    return s.pct_change().fillna(0.0)


def load_benchmark_level(store, code: str, start: date, end: date) -> pd.Series:
    """指数点位序列（择时用），与日收益序列分开维护。"""
    rows = store.query(
        "SELECT ts, close FROM index_bar WHERE index_code = ? AND ts BETWEEN ? AND ?"
        " ORDER BY ts", [code, start, end])
    if not rows:
        raise RuntimeError(f"基准指数 {code} 在 {start}..{end} 无点位数据")
    idx = [r[0].date() if isinstance(r[0], datetime) else r[0] for r in rows]
    return pd.Series([float(r[1]) for r in rows], index=idx, dtype="float64")


def ensure_dirs() -> None:
    for d in (DATA_DIR, REPORT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
