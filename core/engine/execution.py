"""日频事件回测撮合内核（FR-B-01..12 / DETAILED-DESIGN §6）。

回测与模拟盘共用本模块（FR-P-07 / ADR-007）：BrokerBase 提供行情与可交易性，
撮合、账本、拒单留痕完全一致。
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd

from core.engine.accounting import Book
from core.engine.cost import CostModel, q2, q4
from core.engine.panels import Panels
from core.market.tradability import floor_lot, tradable
from core.strategy.base import Ctx, Strategy, TargetPortfolio
from core.strategy.constraints import Constraints, apply_industry_cap, cap_weights

BUY, SELL = "BUY", "SELL"


@dataclass
class BacktestConfig:
    strategy_id: str = "s2_multifactor"
    version: str = "v1"
    params: dict = field(default_factory=dict)
    start: date = date(2016, 1, 4)
    end: date = date(2025, 12, 31)
    universe: str = "LIQUID_1000"
    universe_size: int = 1000
    initial_capital: float = 1_000_000.0
    cost: dict = field(default_factory=lambda: CostModel().to_dict())
    benchmark: str = "000300"
    seed: int = 7
    train_end: date | None = None
    run_id: str = field(default_factory=lambda: "run-" + uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = str(self.start), str(self.end)
        d["train_end"] = str(self.train_end) if self.train_end else None
        return d


class Engine:
    def __init__(self, panels: Panels, ctx: Ctx, strategy: Strategy,
                 cfg: BacktestConfig, constraints: Constraints | None = None):
        self.panels = panels
        self.ctx = ctx
        self.strategy = strategy
        self.cfg = cfg
        self.cost = CostModel.from_dict(cfg.cost)
        self.cons = constraints or Constraints.from_dict(cfg.params.get("constraints", {}))
        self.close_ff = panels.close.ffill()
        self.adj_ff = panels.adj_close.ffill()
        self.open_ff = panels.open.ffill()
        # 每只标的「有真实行情的日序」：退市/长期停牌必须强制清算，不得用陈旧价长期估值
        # （FR-D-09）。用日序 + 二分定位「≤D 的最后一条」，全窗口最后一条会漏掉中途停牌。
        import bisect
        self._bisect = bisect
        close_np = panels.close.to_numpy(dtype="float64", na_value=np.nan)
        self.bar_pos = {sym: np.flatnonzero(~np.isnan(close_np[:, j]))
                        for j, sym in enumerate(panels.symbols)}
        self.day_pos = {d: i for i, d in enumerate(panels.days)}
        self.max_stale_days = int(cfg.params.get("max_stale_days", 20))
        self.orders: list[dict] = []
        self.equity: list[dict] = []
        self.positions_snap: list[dict] = []
        self.notes: list[str] = []
        self.rejected: dict[str, int] = {}
        self.signals: list[dict] = []      # 供未来函数门禁比对（FR-B-13 LAG-1）

    # ---------------------------------------------------------------- 主循环
    def run(self) -> dict:
        p = self.panels
        days = [d for d in p.days if self.cfg.start <= d <= self.cfg.end]
        if len(days) < 2:
            raise ValueError("回测区间交易日不足")
        book = Book(Decimal(str(self.cfg.initial_capital)), self.cost)
        rebalance = set(self.strategy.rebalance_days(self.ctx, days[0], days[-1]))
        pending: list[dict] = []
        bench = self.ctx.benchmark

        closes_cur: dict[str, float] = {}
        for i, D in enumerate(days):
            prev = days[i - 1] if i else None
            if i:
                book.roll_day_open()
            self._liquidate_stale(book, D, closes_cur)
            exec_date = D
            if pending:
                self._execute(pending, book, exec_date)
                pending = []
            closes = {s: float(v) for s, v in self.adj_ff.loc[D].items() if pd.notna(v)}
            nav = book.nav(closes)
            closes_cur = closes
            mv = book.market_value(closes)
            self.equity.append({
                "ts": D, "nav": float(nav / Decimal(str(self.cfg.initial_capital))),
                "cash": float(book.cash), "mv": float(mv),
                "exposure": float(mv / nav) if nav else 0.0,
                "turnover": float(book.traded_gross_today / nav) if nav else 0.0,
                "fee": float(book.trades_fee_today),
            })
            book.reset_day()
            book.check_identity()

            if D in rebalance and i + 1 < len(days):
                pending = self._rebalance(book, D, nav, closes, i, days)
            elif D in rebalance and self.cfg.params.get("signal_only"):
                # 信号模式：末日也要产出目标组合（次日由模拟盘执行），但不生成订单
                self._rebalance(book, D, nav, closes, i, days)
            elif D in rebalance:
                self.notes.append(f"区间末日 {D} 为调仓日但不生成悬空订单（TC-B-25）")
            if self.cfg.params.get("daily_positions") or (D in rebalance and i % 12 == 0):
                self._snapshot(book, D, closes, float(nav))

        eq = pd.DataFrame(self.equity).set_index("ts")
        eq["benchmark_nav"] = (1.0 + bench.reindex(eq.index).fillna(0.0)).cumprod()
        eq["drawdown"] = eq["nav"] / eq["nav"].cummax() - 1.0
        return {
            "equity": eq, "orders": pd.DataFrame(self.orders),
            "positions": pd.DataFrame(self.positions_snap),
            "rejected_summary": self.rejected, "notes": self.notes,
            "signals": self.signals,
            "final_positions": {sym: pos.qty for sym, pos in book.positions.items()},
            "final_nav": float(eq["nav"].iloc[-1]),
            "trade_days": len(eq),
        }

    def _liquidate_stale(self, book: Book, D: date, closes: dict[str, float]) -> None:
        """退市或长期停牌的持仓按最后可得价强制清算，并留痕。"""
        for sym, pos in list(book.positions.items()):
            if not pos.qty:
                continue
            pos_i = self.day_pos.get(D, 0)
            arr = self.bar_pos.get(sym)
            if arr is None or len(arr) == 0:
                continue
            k = self._bisect.bisect_right(arr, pos_i) - 1
            if k < 0:
                continue
            stale = pos_i - int(arr[k])
            delist = self.ctx.meta.get(sym, {}).get("delist_date")
            reason = None
            if delist is not None and D >= delist:
                reason = "DELISTED"
            elif stale > self.max_stale_days:
                reason = "STALE_VALUATION"
            if not reason:
                continue
            px = q4(closes.get(sym, 0.0))
            if px <= 0:
                # 没有可用价格时绝不清零持仓：凭空抹掉股份等于销毁资产（AP-04）
                self.notes.append(f"{D} {sym} 触发 {reason} 但无可用价格，保留持仓待下一日重判")
                continue
            fee = book.sell(D, sym, pos.qty, px, f"liquidate@{D}")
            self.orders.append({
                "run_id": self.cfg.run_id, "ts": D, "exec_date": D, "symbol": sym,
                "side": SELL, "req_qty": pos.qty, "filled_qty": pos.qty,
                "price": float(px), "gross": float(px * pos.qty), "fee": float(fee),
                "status": "LIQUIDATED", "reject_reason": reason})
            self.rejected[reason] = self.rejected.get(reason, 0) + 1
            self.notes.append(f"{D} 强制清算 {sym}（{reason}，最后真实行情滞后 {stale} 交易日）")

    # ---------------------------------------------------------------- 调仓
    def _rebalance(self, book: Book, D: date, nav: Decimal, closes: dict,
                   i: int, days: list[date]) -> list[dict]:
        view = self.ctx.asof(D)
        tp: TargetPortfolio = self.strategy.generate(view, D)
        if tp.cash_ratio is not None and not tp.weights:
            self.notes.append(f"{D} 择时仓位 {tp.cash_ratio:.0%} → 清仓")
            return self._make_orders(book, pd.Series(dtype=float), D, nav, closes)
        cur_w = self._current_weights(book, closes, float(nav))
        scores = pd.Series(tp.weights, dtype=float)
        self.signals.append({"ts": D, "raw": {k: round(float(v), 8)
                                             for k, v in sorted(tp.weights.items())}})
        industry = {s: self.ctx.meta.get(s, {}).get("industry_l1") or "未分类"
                    for s in scores.index}
        target, notes = apply_industry_cap(
            cap_weights(scores.clip(lower=0), self.cons.max_weight),
            industry, self.cons.max_industry_dev, None)
        for n in notes:
            self.notes.append(f"{D} {n}")
        if self.cfg.params.get("signal_only") and D == self.panels.days[-1]:
            return []          # 信号模式末日只记录目标，不构造次日订单
        return self._make_orders(book, target, D, nav, closes)

    def _current_weights(self, book: Book, closes: dict, nav: float) -> pd.Series:
        out = {}
        for s, p in book.positions.items():
            if p.qty and s in closes:
                out[s] = p.qty * closes[s] / nav
        return pd.Series(out, dtype=float)

    def _make_orders(self, book: Book, target_w: pd.Series, D: date,
                     nav: Decimal, closes: dict) -> list[dict]:
        """先卖后买；数量按次日开盘价与整手规则确定（FR-B-04/08）。"""
        exec_day = self._next_day(D)
        opens = self.panels.open.loc[exec_day]
        ac = self.adj_ff.loc[exec_day]
        cc = self.close_ff.loc[exec_day]
        ref = f"{self.cfg.run_id}@{D}"
        sells, buys = [], []
        # 必须定序遍历：set 的迭代顺序随字符串哈希随机化变化，
        # 会让同配置在「不同进程」得到不同成交次序（同进程内反而看不出来）
        symbols = sorted(set(book.positions) | set(target_w.index))
        for s in symbols:
            cur_qty = book.qty(s)
            px_close = closes.get(s)
            tgt_val = float(nav) * float(target_w.get(s, 0.0))
            cur_val = cur_qty * px_close if px_close else 0.0
            delta = tgt_val - cur_val
            px_open = opens.get(s)
            # 目标金额与持仓市值都是复权单位，换算股数必须用同单位的复权开盘价
            scale = (float(ac[s]) / float(cc[s])) if (s in ac.index and s in cc.index
                                                      and pd.notna(ac[s]) and pd.notna(cc[s])
                                                      and float(cc[s]) > 0) else 1.0
            if px_open is None or pd.isna(px_open) or px_open <= 0:
                if abs(delta) > 1:
                    self._reject(s, D, exec_day, BUY if delta > 0 else SELL,
                                 abs(delta) / 100, "NO_BAR", ref)
                continue
            slipped = float(self.cost.exec_price(float(px_open), BUY if delta > 0 else SELL))
            px_adj = slipped * scale
            if delta < -1 and cur_qty > 0:
                q = min(cur_qty, floor_lot(-delta / px_adj))
                if tgt_val < px_adj * 100 * 0.5:        # 目标≈0 → 含零股全卖
                    q = cur_qty
                if q > 0:
                    sells.append({"symbol": s, "side": SELL, "qty": int(q), "px": px_open,
                                  "signal_date": D, "signal_run": ref})
            elif delta > 1:
                q = floor_lot(delta / px_adj)
                if q > 0:
                    buys.append({"symbol": s, "side": BUY, "qty": int(q), "px": px_open,
                                 "priority": float(target_w.get(s, 0.0)),
                                 "signal_date": D, "signal_run": ref})
                else:
                    # 目标金额不足一手：必须留痕，否则资金长期闲置在现金里无人解释
                    self._reject(s, D, exec_day, BUY, 0, "LOT_TOO_LARGE", ref)
        buys.sort(key=lambda x: -x["priority"])
        return sells + buys

    def _next_day(self, D: date) -> date:
        days = self.panels.days
        j = days.index(D)
        if j + 1 >= len(days):
            raise IndexError("无次日")
        return days[j + 1]

    # ---------------------------------------------------------------- 撮合
    def _execute(self, pending: list[dict], book: Book, exec_day: date) -> None:
        rows = self.panels.row(exec_day)
        closes_exec = self.close_ff.loc[exec_day]
        for od in pending:
            sym, side, qty = od["symbol"], od["side"], od["qty"]
            bar = self._bar(rows, sym)
            meta = self.ctx.meta.get(sym, {})
            reason = tradable(side, bar, list_date=meta.get("list_date"),
                              trade_date=exec_day, is_st=bool(meta.get("is_st")),
                              in_blacklist=sym in self.cons.blacklist,
                              min_age_days=int(self.cfg.params.get("min_age_days", 60)))
            if side == SELL and qty > book.sellable(sym):
                reason = "SELLABLE_SHORT"
            if reason:
                self._reject(sym, od["signal_date"], exec_day, side, qty, reason)
                continue
            # 成交价 = 开盘价 × (1 ± 滑点)：滑点必须进价格，否则成本被系统性低估（FR-B-06）
            px_raw = self.cost.exec_price(bar["open"], side)
            adj_px = self._adj_exec_price(exec_day, sym, px_raw)
            if side == BUY:
                max_afford = floor_lot(float(book.cash) / float(adj_px)
                                       / (1.0 + self.cost.fee_rate(side)))
                qty = min(qty, max_afford)
                if qty <= 0:
                    self._reject(sym, od["signal_date"], exec_day, side, od["qty"],
                                 "CASH_SHORT")
                    continue
                fee = book.buy(exec_day, sym, qty, adj_px, od["signal_run"])
            else:
                fee = book.sell(exec_day, sym, qty, adj_px, od["signal_run"])
            gross = q2(adj_px * qty)
            self.orders.append({
                "run_id": self.cfg.run_id, "ts": od["signal_date"],
                "exec_date": exec_day, "symbol": sym, "side": side,
                "req_qty": od["qty"], "filled_qty": qty, "price": float(px_raw),
                "gross": float(gross), "fee": float(fee), "status": "FILLED",
                "reject_reason": None,
            })

    def _adj_exec_price(self, exec_day: date, sym: str, px_raw: Decimal) -> Decimal:
        """真实开盘价折算到当日复权单位：adj_open = raw_open × (adj_close / close)。"""
        ac = self.adj_ff.loc[exec_day].get(sym)
        c = self.close_ff.loc[exec_day].get(sym)
        if ac is None or c is None or pd.isna(ac) or pd.isna(c) or float(c) <= 0:
            return px_raw
        return q4(px_raw * Decimal(str(float(ac) / float(c))))

    def _bar(self, rows: dict[str, pd.Series], sym: str) -> pd.Series | None:
        if sym not in rows["close"].index or pd.isna(rows["close"][sym]):
            return None
        return pd.Series({k: v.get(sym) for k, v in rows.items()} |
                         {"is_suspended": False, "is_final": True})

    def _reject(self, sym: str, signal_date: date, exec_date: date, side: str,
                qty: int, reason: str, ref: str = "") -> dict:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
        rec = {"run_id": self.cfg.run_id, "ts": signal_date,
               "exec_date": exec_date, "symbol": sym, "side": side, "req_qty": int(qty),
               "filled_qty": 0, "price": None, "gross": None, "fee": None,
               "status": "REJECTED", "reject_reason": reason}
        self.orders.append(rec)
        return rec

    def _snapshot(self, book: Book, D: date, closes: dict, nav: float) -> None:
        for s, p in book.positions.items():
            if not p.qty:
                continue
            px = closes.get(s, 0.0)
            self.positions_snap.append({
                "ts": D, "symbol": s, "qty": p.qty, "sellable_qty": p.sellable,
                "cost": float(p.cost / p.qty), "mv": p.qty * px,
                "weight": p.qty * px / nav if nav else 0.0,
            })


def run_backtest(store, strategy: Strategy, cfg: BacktestConfig,
                 panels: Panels | None = None, factors: dict[str, pd.DataFrame] | None = None,
                 meta: dict[str, dict] | None = None, benchmark: pd.Series | None = None
                 ) -> dict:
    """服务级入口：装配 Ctx 并跑引擎，落库产物。"""
    from core.config.settings import load_benchmark_returns
    from core.engine import panels as panel_mod
    panels = panels or panel_mod.load(store, cfg.start, cfg.end)
    benchmark = benchmark if benchmark is not None else load_benchmark_returns(
        store, cfg.benchmark, cfg.start, cfg.end)
    ctx = Ctx(panels, factors or {}, meta or {}, benchmark)
    eng = Engine(panels, ctx, strategy, cfg)
    out = eng.run()
    out["config"] = cfg.to_dict()
    return out
