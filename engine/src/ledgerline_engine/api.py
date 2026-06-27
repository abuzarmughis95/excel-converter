"""Public API surface of the accounting engine.

Re-exports the domain types and operations callers should use. Importing from
``ledgerline_engine.api`` gives a stable surface independent of internal module
layout.
"""

from ledgerline_engine.account import (
    Account,
    AccountType,
    ControlKind,
    NormalBalance,
    normal_balance_for,
)
from ledgerline_engine.depreciation import (
    DepreciationError,
    DepreciationLine,
    DepreciationMethod,
    FixedAssetSpec,
    period_charge,
    schedule,
)
from ledgerline_engine.ledger import (
    LedgerNotBalancedError,
    TrialBalanceRow,
    trial_balance,
)
from ledgerline_engine.money import Money, Rounding, sum_money
from ledgerline_engine.period import (
    IllegalPeriodTransitionError,
    Period,
    PeriodStatus,
)
from ledgerline_engine.posting import (
    EmptyPostingError,
    InvalidLineError,
    Posting,
    PostingError,
    PostingLine,
    UnbalancedPostingError,
)
from ledgerline_engine.reports import (
    BalanceSheet,
    ProfitAndLoss,
    ReportLine,
    ReportNotBalancedError,
    balance_sheet,
    profit_and_loss,
)
from ledgerline_engine.vat import (
    VatDirection,
    VatEntry,
    VatReturn,
    compute_vat_return,
)

__all__ = [
    "Account",
    "AccountType",
    "BalanceSheet",
    "ControlKind",
    "DepreciationError",
    "DepreciationLine",
    "DepreciationMethod",
    "FixedAssetSpec",
    "EmptyPostingError",
    "IllegalPeriodTransitionError",
    "InvalidLineError",
    "LedgerNotBalancedError",
    "Money",
    "NormalBalance",
    "Period",
    "PeriodStatus",
    "Posting",
    "PostingError",
    "PostingLine",
    "ProfitAndLoss",
    "ReportLine",
    "ReportNotBalancedError",
    "Rounding",
    "TrialBalanceRow",
    "UnbalancedPostingError",
    "VatDirection",
    "VatEntry",
    "VatReturn",
    "balance_sheet",
    "compute_vat_return",
    "normal_balance_for",
    "period_charge",
    "profit_and_loss",
    "schedule",
    "sum_money",
    "trial_balance",
]
