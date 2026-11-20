"""持仓与现金账本（ADR-014 修订口径）。

钱统一记在**复权单位**上，真实价只用于整手数量与可交易性判定：
- 建仓：cash −= qty × 复权开盘价 + 费用；持仓市值 = qty × 复权收盘；
- 因此净值增长 = 后复权（含分红与送转）总收益，天然不会「价格 + 分红」重复计入（TC-B-03），
  也不会出现送股日净值腰斩；
- 旧实现按「市值 ×(r_adj − r_price)」计提分红，只对**等比法**复权成立；东财是**差额法**
  （adj ≈ a + b·raw），该式会把除权/送转错当分红反复计入，实测造成净值偏离（已废弃）。
- 现金恒等式：cash == 初始资金 + Σ 流水金额，每日断言，不用调整项抹平（FR-P-05 同源逻辑）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from core.engine.cost import CostModel, q2

INITIAL = "INITIAL"


@dataclass
class Position:
    symbol: str
    qty: int = 0
    sellable: int = 0
    cost: Decimal = Decimal("0")        # 加权成本（真实价，仅用于展示与盈亏归因）

    @property
    def book_value_per_share(self) -> Decimal:
        return self.cost / self.qty if self.qty else Decimal("0")


@dataclass
class Book:
    initial_capital: Decimal
    cost_model: CostModel
    cash: Decimal = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    ledger: list[dict] = field(default_factory=list)
    trades_fee_today: Decimal = Decimal("0")
    traded_gross_today: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.cash = Decimal(self.initial_capital)
        self.ledger.append({"kind": INITIAL, "symbol": "*", "qty": 0,
                            "amount": float(self.cash), "ref": "initial"})

    # ---------------------------------------------------------------- 查询
    def qty(self, symbol: str) -> int:
        return self.positions[symbol].qty if symbol in self.positions else 0

    def sellable(self, symbol: str) -> int:
        return self.positions[symbol].sellable if symbol in self.positions else 0

    def market_value(self, closes: dict[str, float]) -> Decimal:
        return q2(sum(Decimal(str(p.qty)) * Decimal(str(closes[s]))
                      for s, p in self.positions.items() if p.qty and s in closes))

    def nav(self, closes: dict[str, float]) -> Decimal:
        return q2(self.cash + self.market_value(closes))

    # ---------------------------------------------------------------- 交易
    def buy(self, ts: date, symbol: str, qty: int, price: Decimal, ref: str) -> Decimal:
        gross = q2(price * qty)
        fee = self.cost_model.fee(gross, "BUY")
        self.cash = q2(self.cash - gross - fee)
        p = self.positions.setdefault(symbol, Position(symbol))
        p.cost = q2(p.cost + gross)
        p.qty += qty                       # 当日买入不可卖（T+1）
        self.ledger.append({"kind": "BUY", "symbol": symbol, "qty": qty,
                            "amount": float(-(gross + fee)), "ref": ref})
        self.trades_fee_today += fee
        self.traded_gross_today += gross
        return fee

    def sell(self, ts: date, symbol: str, qty: int, price: Decimal, ref: str) -> Decimal:
        p = self.positions[symbol]
        gross = q2(price * qty)
        fee = self.cost_model.fee(gross, "SELL")
        self.cash = q2(self.cash + gross - fee)
        book_ps = p.book_value_per_share
        p.cost = q2(p.cost - book_ps * qty)
        p.qty -= qty
        p.sellable = max(0, p.sellable - qty)
        if p.qty == 0:
            p.cost = Decimal("0")
        self.ledger.append({"kind": "SELL", "symbol": symbol, "qty": -qty,
                            "amount": float(gross - fee), "ref": ref})
        self.trades_fee_today += fee
        self.traded_gross_today += gross
        return fee

    # ---------------------------------------------------------------- 日终
    def roll_day_open(self) -> None:
        """新交易日：昨日买入转为可卖（T+1）。"""
        for p in self.positions.values():
            p.sellable = p.qty

    def accrue_dividends(self, prev_closes: dict[str, float], adj_r: dict[str, float],
                         price_r: dict[str, float]) -> Decimal:
        """把总收益与价格收益之差（= 分红）计提进现金。"""
        total = Decimal("0")
        for s, p in self.positions.items():
            if not p.qty or s not in prev_closes:
                continue
            mv = Decimal(str(p.qty)) * Decimal(str(prev_closes[s]))
            extra = adj_r.get(s, 0.0) - price_r.get(s, 0.0)
            if abs(extra) < 1e-9:
                continue
            amt = q2(mv * Decimal(str(extra)))
            if amt:
                total += amt
                self.ledger.append({"kind": "DIVIDEND", "symbol": s, "qty": 0,
                                    "amount": float(amt), "ref": "adj-price spread"})
        if total:
            self.cash = q2(self.cash + total)
        return total

    def cash_from_ledger(self) -> Decimal:
        return q2(sum(Decimal(str(r["amount"])) for r in self.ledger))

    def check_identity(self) -> None:
        """现金必须等于流水之和（AP-04 / FR-P-05 同源断言）。"""
        diff = self.cash - self.cash_from_ledger()
        if abs(diff) > Decimal("0.01"):
            raise ReconDiff(f"现金与流水不平：diff={diff}")

    def reset_day(self) -> None:
        self.trades_fee_today = Decimal("0")
        self.traded_gross_today = Decimal("0")


class ReconDiff(RuntimeError):
    """QUANT-P-001 对账超阈值。"""
