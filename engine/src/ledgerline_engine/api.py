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

__all__ = [
    "Account",
    "AccountType",
    "ControlKind",
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
    "Rounding",
    "TrialBalanceRow",
    "UnbalancedPostingError",
    "normal_balance_for",
    "sum_money",
    "trial_balance",
]
