from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TrialBalanceAccount:
    row_number: int
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    level: int
    parent_code: str | None
    is_leaf: bool
    is_summary: bool

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "debit": float(self.debit),
            "credit": float(self.credit),
            "balance": float(self.balance),
            "level": self.level,
            "parent_code": self.parent_code,
            "is_leaf": self.is_leaf,
            "is_summary": self.is_summary,
        }