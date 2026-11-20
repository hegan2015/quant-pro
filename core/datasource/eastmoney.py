"""东财 push2/push2his 直连 adapter（P1 主数据源）。

为什么不用 akshare：接口层自己写可控且少一层依赖漂移，字段口径直接对齐（东财 f51..f61）。
复权口径：同一区间分别取 fqt=0（原始价）与 fqt=2（后复权价），比值即累积因子，
再归一到「上市首日因子=1」，从而撮合用真实价、净值用连续价（FR-B-03 / ADR-004）。
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from datetime import date, datetime

import httpx
import pandas as pd

KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
INDEXES = {
    "000300": "1.000300", "000905": "1.000905", "000852": "1.000852",
    "000001": "1.000001", "399006": "0.399006", "399001": "0.399001",
}
# fs 参数：沪深京 A 股（主板/创业板/科创板/北交所）
LIST_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"


def secid(symbol: str) -> str:
    """'600519.SH' → '1.600519'；北交所与深市为 0.*"""
    code, _, exch = symbol.partition(".")
    if exch == "SH":
        return f"1.{code}"
    if exch == "SZ":
        return f"0.{code}"
    if code[0] in ("6", "9", "5"):
        return f"1.{code}"
    return f"0.{code}"


def board(symbol: str) -> str:
    code = symbol.split(".")[0]
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301", "302")):
        return "gem"
    if code.startswith(("8", "4", "920")):
        return "bse"
    if code.startswith(("60", "00")):
        return "main"
    return "other"


def exchange(symbol: str) -> str:
    code = symbol.split(".")[0]
    if code.startswith(("6", "9", "5")):
        return "SSE"
    if code.startswith(("4", "8")) or code.startswith("920"):
        return "BSE"
    return "SZSE"


class RateLimit:
    """令牌桶 + 抖动退避（FR-O-05：默认 5 req/s）。"""

    def __init__(self, rate: float = 5.0, burst: int = 8):
        self.rate, self.burst = rate, burst
        self.tokens = float(burst)
        self.updated = time.monotonic()

    def acquire(self) -> None:
        while True:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            time.sleep(max(0.0, (1 - self.tokens) / self.rate) + random.uniform(0, 0.02))


class EastmoneyClient:
    def __init__(self, rate: float = 5.0, timeout: float = 20.0, retries: int = 3):
        self.rate = RateLimit(rate)
        self.timeout = timeout
        self.retries = retries
        self.headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            # trust_env=False：本机 NO_PROXY 含 IPv6 字面量 [::1]，httpx 解析环境变量会抛
            # InvalidURL；数据源走直连即可（已实测 200）。
            self._client = httpx.Client(headers=self.headers, timeout=self.timeout,
                                        trust_env=False)
        return self._client

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def _get(self, url: str, params: dict) -> dict:
        last = None
        for attempt in range(self.retries):
            self.rate.acquire()
            try:
                r = self.client.get(url, params=params)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json() or {}
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                time.sleep(0.4 * (2 ** attempt) + random.uniform(0, 0.3))
        raise DataSourceUnavailable(f"东财接口连续失败 {self.retries} 次：{last}")

    # ------------------------------------------------------------------ 行情
    def kline(self, sid: str, beg: date, end: date, fqt: int) -> pd.DataFrame:
        data = self._get(KLINE_URL, {
            "secid": sid, "fields1": FIELDS1, "fields2": FIELDS2,
            "klt": "101", "fqt": str(fqt), "beg": beg.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"), "lmt": "100000",
        }).get("data") or {}
        rows = []
        for line in data.get("klines") or []:
            p = line.split(",")
            if len(p) < 7:
                continue
            # 东财 kline 字段顺序：f51 日期, f52 开, f53 收, f54 高, f55 低,
            # f56 量(手), f57 额(元), f58 振幅%, f59 涨跌幅%, f60 涨跌额, f61 换手率%
            rows.append({
                "ts": p[0], "open": p[1], "close": p[2], "high": p[3], "low": p[4],
                "volume": p[5], "amount": p[6],
                "pct_chg": p[8] if len(p) > 8 else None,
                "turnover": p[10] if len(p) > 10 else None,
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"]).dt.date
        for c in ("open", "high", "low", "close", "amount", "pct_chg", "turnover"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["volume"] = (pd.to_numeric(df["volume"], errors="coerce") * 100).astype("int64")
        # 流通股本 = 成交量 / 换手率（日频 PIT 股本估计，避免用当前股本回算历史市值造成前视）
        df["float_share"] = (df["volume"] / (df["turnover"] / 100.0)).where(
            df["turnover"] > 0)
        df.attrs["pre_k_price"] = data.get("preKPrice")
        df.attrs["name"] = data.get("name")
        return df

    def bars(self, symbol: str, beg: date, end: date) -> pd.DataFrame:
        """原始价 + 后复权价 → 含 adj_factor / limit_up / limit_down 的入库形态。"""
        sid = secid(symbol)
        raw = self.kline(sid, beg, end, fqt=0)
        if raw.empty:
            return raw
        hfq = self.kline(sid, beg, end, fqt=2)
        merged = raw.merge(hfq[["ts", "close"]].rename(columns={"close": "hfq_close"}),
                           on="ts", how="left")
        ratio = merged["hfq_close"] / merged["close"]
        base = ratio.dropna().iloc[0] if ratio.notna().any() else 1.0
        merged["adj_factor"] = (ratio / base).fillna(1.0) if base else 1.0

        merged["symbol"] = symbol
        merged["float_share"] = raw.set_index("ts")["float_share"].reindex(merged["ts"]).values
        merged["pre_close"] = merged["close"].shift(1)
        if merged["pre_close"].isna().iloc[0] and raw.attrs.get("pre_k_price"):
            merged.loc[0, "pre_close"] = float(raw.attrs["pre_k_price"])
        up, down = limit_pct(symbol, bool("ST" in str(raw.attrs.get("name", ""))))
        merged["limit_up"] = (merged["pre_close"] * (1 + up)).round(2)
        merged["limit_down"] = (merged["pre_close"] * (1 - down)).round(2)
        merged["is_suspended"] = False
        merged["is_final"] = True
        merged["source"] = "eastmoney"
        merged["fetched_at"] = datetime.now()
        merged["data_version"] = "fetch-" + datetime.now().strftime("%Y%m%d%H%M")
        return merged[["ts", "symbol", "open", "high", "low", "close", "pre_close",
                       "volume", "amount", "adj_factor", "float_share", "limit_up", "limit_down",
                       "is_suspended", "is_final", "source", "fetched_at", "data_version"]]

    def index_bars(self, code: str, beg: date, end: date) -> pd.DataFrame:
        df = self.kline(INDEXES[code], beg, end, fqt=0)
        if df.empty:
            return df
        out = df[["ts", "close", "amount"]].copy()
        out["index_code"] = code
        out["data_version"] = "fetch-" + datetime.now().strftime("%Y%m%d%H%M")
        return out[["ts", "index_code", "close", "amount"]]

    # ------------------------------------------------------------------ 主数据
    def stock_list(self) -> pd.DataFrame:
        rows, page = [], 1
        while True:
            data = self._get(LIST_URL, {
                "pn": str(page), "pz": "500", "po": "0", "np": "1", "fltt": "2",
                "invt": "2", "fid": "f12", "fs": LIST_FS,
                "fields": "f12,f13,f14,f26,f100",
            }).get("data") or {}
            diff = data.get("diff") or []
            if not diff:
                break
            rows.extend(diff)
            if len(rows) >= int(data.get("total") or 0):
                break
            page += 1
        df = pd.DataFrame(rows).rename(columns={
            "f12": "code", "f13": "market", "f14": "name", "f26": "list_date_raw",
            "f100": "industry"})
        df["list_date_raw"] = pd.to_numeric(df.get("list_date_raw"), errors="coerce")
        if df.empty:
            return df
        df["symbol"] = df.apply(
            lambda r: f"{r['code']}.{'SH' if int(r['market']) == 1 else 'SZ'}", axis=1)
        df["exchange"] = df["symbol"].map(exchange)
        df["board"] = df["symbol"].map(board)
        df["is_st"] = df["name"].str.contains("ST", na=False)
        return df[["symbol", "name", "exchange", "board", "is_st", "list_date_raw", "industry"]]

    def list_dates(self, symbol: str, beg: date, end: date) -> list[date]:
        df = self.kline(secid(symbol), beg, end, fqt=0)
        return [] if df.empty else list(df["ts"])


def limit_pct(symbol: str, is_st: bool) -> tuple[float, float]:
    """涨跌停幅度（近似：新股上市前 5 日不设限由 tradability 处理）。"""
    b = board(symbol)
    if b == "bse":
        return 0.30, 0.30
    if b in ("gem", "star"):
        return 0.20, 0.20
    if is_st:
        return 0.05, 0.05
    return 0.10, 0.10


class DataSourceUnavailable(RuntimeError):
    """QUANT-D-003 外部源失败（含限流）。"""


async def gather_bars(client: EastmoneyClient, symbols: list[str], beg: date, end: date,
                      concurrency: int = 8) -> pd.DataFrame:
    """线程池并发抓取（adapter 为同步 httpx，用 asyncio.to_thread 复用限流桶）。"""
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    async def one(sym: str) -> pd.DataFrame:
        async with sem:
            try:
                return await loop.run_in_executor(None, client.bars, sym, beg, end)
            except DataSourceUnavailable:
                return pd.DataFrame()

    chunks = []
    for i in range(0, len(symbols), 200):
        got = await asyncio.gather(*[one(s) for s in symbols[i:i + 200]])
        chunks.extend(g for g in got if not g.empty)
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def fetch_many(client: EastmoneyClient, symbols: list[str], beg: date, end: date,
               concurrency: int = 8) -> pd.DataFrame:
    return asyncio.run(gather_bars(client, symbols, beg, end, concurrency))


def ceil_lot(qty: float) -> int:
    return int(math.floor(qty / 100) * 100)
