"""Trial balance computation over a set of postings.

Pure function: given accounts and postings, produce each account's net balance
on its normal side, and assert the whole ledger balances to zero. This is the
first report derived from the engine; P&L and balance sheet build on it in later
tickets. No persistence — postings are passed in.
"""

from __future__ import annotations

from dataclasses import dataclass

from ledgerline_engine.account import Account, NormalBalance
from ledgerline_engine.money import Money, sum_money
from ledgerline_engine.posting import Posting


class LedgerNotBalancedError(Exception):
    """The aggregate of postings does not balance to zero (a bug or bad data)."""


@dataclass(frozen=True, slots=True)
class TrialBalanceRow:
    """One account's NET position on the trial balance, in base currency.

    A trial balance reports each account's net balance on a single side: an
    account whose debits exceed its credits shows the difference in ``debit``
    (and zero in ``credit``), and vice versa. An account that nets to zero shows
    zero on both sides. This matches how a trial balance is presented and read.
    """

    account: Account
    debit: Money
    credit: Money

    @property
    def net_on_normal_side(self) -> Money:
        """Net balance expressed on the account's normal side."""
        if self.account.normal_balance is NormalBalance.DEBIT:
            return self.debit.subtract(self.credit)
        return self.credit.subtract(self.debit)


def trial_balance(
    accounts: list[Account],
    postings: list[Posting],
    *,
    base_currency: str,
) -> list[TrialBalanceRow]:
    """Compute the trial balance (in base currency) for the given postings.

    Raises :class:`LedgerNotBalancedError` if total debits != total credits,
    which should be impossible given postings are individually balanced — it is
    a defensive cross-check.
    """
    by_code: dict[str, Account] = {a.code: a for a in accounts}
    debit_totals: dict[str, list[Money]] = {a.code: [] for a in accounts}
    credit_totals: dict[str, list[Money]] = {a.code: [] for a in accounts}

    for posting in postings:
        for line in posting.lines:
            code = line.account.code
            if code not in by_code:
                msg = f"Posting references unknown account {code}"
                raise LedgerNotBalancedError(msg)
            if line.is_debit:
                debit_totals[code].append(line.base_amount)
            else:
                credit_totals[code].append(line.base_amount)

    rows = []
    for code in by_code:
        gross_debit = sum_money(debit_totals[code], base_currency)
        gross_credit = sum_money(credit_totals[code], base_currency)
        # Net each account onto a single side: an account is shown with its net
        # debit OR net credit, never both (the other side is zero).
        net = gross_debit.subtract(gross_credit)
        if net.sign >= 0:
            row_debit, row_credit = net, Money.zero(base_currency)
        else:
            row_debit, row_credit = Money.zero(base_currency), net.negate()
        rows.append(
            TrialBalanceRow(account=by_code[code], debit=row_debit, credit=row_credit)
        )

    total_debit = sum_money([r.debit for r in rows], base_currency)
    total_credit = sum_money([r.credit for r in rows], base_currency)
    if total_debit != total_credit:
        msg = f"Trial balance does not balance: debits {total_debit} != credits {total_credit}"
        raise LedgerNotBalancedError(msg)

    return rows
