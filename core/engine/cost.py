"""成本模型（FR-B-06 / DETAILED-DESIGN §6.3）。

金额一律 Decimal 到分，避免浮点累计漂移；滑点作用于成交价而非事后扣减，
使「现金 = Σ 流水」恒等式可直接断言（§6.2）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TICK4 = Decimal("0.0001")


def q2(x: Decimal | float | str) -> Decimal:
    """真实价与金额：分（A 股最小报价单位 0.01 元）。"""
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(x: Decimal | float | str) -> Decimal:
    """复权单位价格：4 位小数。压到 2 位会引入 ~0.05% 的单笔漂移。"""
    return Decimal(str(x)).quantize(TICK4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostModel:
    commission_bp: Decimal = Decimal("2.5")     # 双边，万 2.5
    min_commission: Decimal = Decimal("5")      # 单笔最低 5 元
    stamp_tax_sell_bp: Decimal = Decimal("5")   # 卖出单边 0.05%（2023-08 起）
    transfer_bp: Decimal = Decimal("0.1")       # 过户费双边
    slippage_bp: Decimal = Decimal("5")         # 滑点

    def __post_init__(self) -> None:
        """配置/JSON 常给字符串或浮点，统一转 Decimal，避免 str / Decimal 运算失败。"""
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, Decimal(str(getattr(self, name))))

    @property
    def _comm(self) -> Decimal:
        return self.commission_bp / Decimal("10000")

    @property
    def _stamp(self) -> Decimal:
        return self.stamp_tax_sell_bp / Decimal("10000")

    @property
    def _transfer(self) -> Decimal:
        return self.transfer_bp / Decimal("10000")

    @property
    def _slip(self) -> Decimal:
        return self.slippage_bp / Decimal("10000")

    def fee_rate(self, side: str) -> float:
        """近似费率（含过户费与印花税），用于可负担数量估算。"""
        base = float(self._comm + self._transfer)
        return base + (float(self._stamp) if side == "SELL" else 0.0)

    def exec_price(self, price: Decimal | float, side: str) -> Decimal:
        p = Decimal(str(price))
        return q2(p * (1 + self._slip) if side == "BUY" else p * (1 - self._slip))

    def fee(self, gross: Decimal, side: str) -> Decimal:
        gross = Decimal(str(gross))
        comm = max(gross * self._comm, self.min_commission)
        transfer = gross * self._transfer
        stamp = gross * self._stamp if side == "SELL" else Decimal("0")
        return q2(comm + transfer + stamp)

    def commission_breakdown(self, gross: Decimal, side: str) -> dict:
        gross = Decimal(str(gross))
        return {
            "commission": float(q2(max(gross * self._comm, self.min_commission))),
            "transfer": float(q2(gross * self._transfer)),
            "stamp_tax": float(q2(gross * self._stamp)) if side == "SELL" else 0.0,
        }

    def to_dict(self) -> dict:
        return {k: float(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict) -> "CostModel":
        return cls(**{k: Decimal(str(v)) for k, v in d.items()})
