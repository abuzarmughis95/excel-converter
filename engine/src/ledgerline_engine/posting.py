"""The double-entry Posting (AC-03) — the heart of the engine.

A ``Posting`` is constructed from lines and CANNOT exist unbalanced: the
constructor enforces that, per currency, total debits equal total credits, and
that total base-currency debits equal total base-currency credits. A line is a
debit XOR a credit (never both, never neither). Illegal states are
unrepresentable — you cannot hold an unbalanced Posting object.

This invariant is the single most important rule in the system and is enforced
here at the type/constructor level (the primary gate), re-checked by a database
trigger at commit, and re-validated server-side on sync — three independent
layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerline_engine.account import Account
from ledgerline_engine.money import Money, sum_money


class PostingError(Exception):
    """Base class for posting-construction failures."""


class UnbalancedPostingError(PostingError):
    """Debits do not equal credits (in transaction or base currency)."""


class InvalidLineError(PostingError):
    """A line is malformed (both/neither side, inactive account, etc.)."""


class EmptyPostingError(PostingError):
    """A posting must have at least two lines."""


@dataclass(frozen=True, slots=True)
class PostingLine:
    """One leg of a posting: a debit XOR a credit against an account.

    ``amount`` is in the transaction currency; ``base_amount`` is the same value
    converted to the entity's base/reporting currency (equal when there is no
    FX). Exactly one of debit/credit is true.
    """

    account: Account
    amount: Money
    base_amount: Money
    is_debit: bool
    narrative: str | None = None

    def __post_init__(self) -> None:
        if self.amount.sign < 0 or self.base_amount.sign < 0:
            msg = "Line amounts must be non-negative; use the debit/credit side"
            raise InvalidLineError(msg)
        if self.amount.is_zero:
            msg = "Line amount must be non-zero"
            raise InvalidLineError(msg)
        if not self.account.is_active:
            msg = f"Account {self.account.code} is not active"
            raise InvalidLineError(msg)

    @property
    def is_credit(self) -> bool:
        return not self.is_debit


@dataclass(frozen=True, slots=True)
class Posting:
    """A balanced set of posting lines. Unconstructable unless it balances."""

    lines: tuple[PostingLine, ...]
    currency: str
    base_currency: str
    _checked: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.lines) < 2:
            msg = "A posting must have at least two lines"
            raise EmptyPostingError(msg)

        debits = [ln.amount for ln in self.lines if ln.is_debit]
        credits = [ln.amount for ln in self.lines if ln.is_credit]
        base_debits = [ln.base_amount for ln in self.lines if ln.is_debit]
        base_credits = [ln.base_amount for ln in self.lines if ln.is_credit]

        if not debits or not credits:
            msg = "A posting must have at least one debit and one credit"
            raise UnbalancedPostingError(msg)

        total_debit = sum_money(debits, self.currency)
        total_credit = sum_money(credits, self.currency)
        if total_debit != total_credit:
            msg = (
                f"Debits ({total_debit}) do not equal credits ({total_credit}) "
                f"in {self.currency}"
            )
            raise UnbalancedPostingError(msg)

        total_base_debit = sum_money(base_debits, self.base_currency)
        total_base_credit = sum_money(base_credits, self.base_currency)
        if total_base_debit != total_base_credit:
            msg = (
                f"Base-currency debits ({total_base_debit}) do not equal "
                f"base credits ({total_base_credit}) in {self.base_currency}"
            )
            raise UnbalancedPostingError(msg)

    @classmethod
    def of(cls, lines: list[PostingLine], *, base_currency: str) -> Posting:
        """Construct a Posting from lines, inferring the transaction currency.

        All non-base line amounts must share one currency.
        """
        if not lines:
            msg = "A posting must have at least two lines"
            raise EmptyPostingError(msg)
        currencies = {ln.amount.currency for ln in lines}
        if len(currencies) != 1:
            msg = f"All lines must share one transaction currency, got {currencies}"
            raise InvalidLineError(msg)
        currency = next(iter(currencies))
        return cls(tuple(lines), currency=currency, base_currency=base_currency)

    @property
    def total_debit(self) -> Money:
        return sum_money([ln.amount for ln in self.lines if ln.is_debit], self.currency)

    @property
    def total_credit(self) -> Money:
        return sum_money([ln.amount for ln in self.lines if ln.is_credit], self.currency)
