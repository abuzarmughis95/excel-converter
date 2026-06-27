import { useCallback, useEffect, useMemo, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button } from '../components/ui/index.js';
import { ApiError } from '../lib/api-client.js';
import { errorMessage } from '../lib/errors.js';
import type { AccountResponse, JournalResponse, TrialBalanceRow } from '../lib/api-types.js';
import {
  formatMinorPlain as formatMinor,
  parseMajorToMinor as toMinor,
} from '../lib/money.js';

/** A single editable grid row in the journal entry form. */
interface GridRow {
  key: number;
  accountId: string;
  debit: string;
  credit: string;
}

function blankRow(key: number): GridRow {
  return { key, accountId: '', debit: '', credit: '' };
}

/**
 * Journal Entry — the spreadsheet-style data-entry screen. Type debit/credit
 * rows against accounts; the running totals update live and the Post button is
 * only enabled when the entry balances. Posting is validated again by the
 * backend's accounting engine.
 */
export function JournalEntryScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [journals, setJournals] = useState<JournalResponse[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalanceRow[]>([]);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [narrative, setNarrative] = useState('');
  const [rows, setRows] = useState<GridRow[]>([blankRow(1), blankRow(2)]);
  const [nextKey, setNextKey] = useState(3);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [accs, jrnls, tb] = await Promise.all([
        api.listAccounts(companyId),
        api.listJournals(companyId),
        api.trialBalance(companyId),
      ]);
      setAccounts(accs.filter((a) => a.is_active));
      setJournals(jrnls);
      setTrialBalance(tb);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const totals = useMemo(() => {
    let debit = 0;
    let credit = 0;
    let valid = true;
    for (const r of rows) {
      const d = toMinor(r.debit);
      const c = toMinor(r.credit);
      if (Number.isNaN(d) || Number.isNaN(c)) {
        valid = false;
        continue;
      }
      debit += d;
      credit += c;
    }
    return { debit, credit, valid, balanced: valid && debit === credit && debit > 0 };
  }, [rows]);

  function updateRow(key: number, patch: Partial<GridRow>): void {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addRow(): void {
    setRows((prev) => [...prev, blankRow(nextKey)]);
    setNextKey((k) => k + 1);
  }

  function removeRow(key: number): void {
    setRows((prev) => (prev.length > 2 ? prev.filter((r) => r.key !== key) : prev));
  }

  async function onPost(): Promise<void> {
    if (companyId === null || !totals.balanced) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const lines = rows
        .filter((r) => r.accountId !== '' && (toMinor(r.debit) > 0 || toMinor(r.credit) > 0))
        .map((r) => ({
          account_id: r.accountId,
          debit_minor: toMinor(r.debit),
          credit_minor: toMinor(r.credit),
        }));
      const created = await api.createJournal(companyId, {
        journal_date: date,
        narrative: narrative === '' ? null : narrative,
        lines,
      });
      await api.postJournal(companyId, created.id);
      // Reset the form and refresh.
      setRows([blankRow(nextKey), blankRow(nextKey + 1)]);
      setNextKey((k) => k + 2);
      setNarrative('');
      await reload();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Failed to post journal. Check the entry balances.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function onUnpost(journalId: string): Promise<void> {
    if (companyId === null) {
      return;
    }
    const reason = window.prompt('Reason for unposting this journal?');
    if (reason === null || reason.trim() === '') {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.unpostJournal(companyId, journalId, reason.trim());
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to unpost.'));
    } finally {
      setBusy(false);
    }
  }

  async function onReverse(journalId: string): Promise<void> {
    if (companyId === null) {
      return;
    }
    const reason = window.prompt('Reason for reversing this journal?');
    if (reason === null || reason.trim() === '') {
      return;
    }
    const when = window.prompt('Reversal date (YYYY-MM-DD), or leave blank for the original date.');
    if (when === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.reverseJournal(
        companyId,
        journalId,
        reason.trim(),
        when.trim() === '' ? null : when.trim(),
      );
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to reverse.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  if (accounts.length === 0) {
    return (
      <section aria-live="polite">
        <p>Add some accounts first (Bookkeeping screen) before entering journals.</p>
      </section>
    );
  }

  const difference = totals.debit - totals.credit;

  return (
    <section aria-live="polite" className="journal-screen">
      <div className="journal-header-row">
        <label>
          Date{' '}
          <input
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
            }}
          />
        </label>
        <label className="journal-narrative">
          Narrative{' '}
          <input
            type="text"
            placeholder="Description (optional)"
            value={narrative}
            onChange={(e) => {
              setNarrative(e.target.value);
            }}
          />
        </label>
      </div>

      <table className="journal-grid">
        <thead>
          <tr>
            <th>Account</th>
            <th className="num">Debit</th>
            <th className="num">Credit</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>
                <select
                  value={r.accountId}
                  onChange={(e) => {
                    updateRow(r.key, { accountId: e.target.value });
                  }}
                  aria-label="Account"
                >
                  <option value="">— select account —</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} · {a.name}
                    </option>
                  ))}
                </select>
              </td>
              <td className="num">
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="0.00"
                  value={r.debit}
                  onChange={(e) => {
                    updateRow(r.key, { debit: e.target.value, credit: '' });
                  }}
                  aria-label="Debit"
                />
              </td>
              <td className="num">
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="0.00"
                  value={r.credit}
                  onChange={(e) => {
                    updateRow(r.key, { credit: e.target.value, debit: '' });
                  }}
                  aria-label="Credit"
                />
              </td>
              <td>
                <button
                  type="button"
                  className="journal-row-remove"
                  onClick={() => {
                    removeRow(r.key);
                  }}
                  disabled={rows.length <= 2}
                  aria-label="Remove row"
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>
              <Button variant="secondary" onClick={addRow}>
                + Add row
              </Button>
            </td>
            <td className="num">{formatMinor(totals.debit)}</td>
            <td className="num">{formatMinor(totals.credit)}</td>
            <td />
          </tr>
        </tfoot>
      </table>

      <div className="journal-balance-bar">
        {totals.balanced ? (
          <span className="balanced">Balanced ✓</span>
        ) : (
          <span className="unbalanced">
            {totals.valid
              ? `Out of balance by ${formatMinor(Math.abs(difference))}`
              : 'Enter valid amounts'}
          </span>
        )}
        <Button
          className="journal-post"
          onClick={() => void onPost()}
          disabled={!totals.balanced || busy}
        >
          {busy ? 'Posting…' : 'Post journal'}
        </Button>
      </div>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      <div className="journal-lower">
        <div className="journal-recent">
          <h3>Recent journals</h3>
          {journals.length === 0 ? (
            <p>No journals yet.</p>
          ) : (
            <ul className="journal-list">
              {journals.slice(0, 8).map((j) => (
                <li key={j.id}>
                  <span>
                    {j.journal_date} · {j.narrative ?? j.journal_type} ·{' '}
                    {j.is_posted ? 'Posted' : 'Draft'}
                  </span>
                  {j.is_posted && (
                    <span className="journal-actions">
                      <Button variant="secondary" disabled={busy} onClick={() => void onUnpost(j.id)}>
                        Unpost
                      </Button>
                      <Button variant="secondary" disabled={busy} onClick={() => void onReverse(j.id)}>
                        Reverse
                      </Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="journal-tb">
          <h3>Trial balance</h3>
          <table className="devices-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account</th>
                <th className="num">Debit</th>
                <th className="num">Credit</th>
              </tr>
            </thead>
            <tbody>
              {trialBalance
                .filter((r) => r.debit_minor !== 0 || r.credit_minor !== 0)
                .map((r) => (
                  <tr key={r.account_code}>
                    <td>{r.account_code}</td>
                    <td>{r.account_name}</td>
                    <td className="num">
                      {r.debit_minor ? formatMinor(r.debit_minor) : ''}
                    </td>
                    <td className="num">
                      {r.credit_minor ? formatMinor(r.credit_minor) : ''}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
