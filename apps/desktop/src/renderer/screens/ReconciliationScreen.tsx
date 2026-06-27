import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button } from '../components/ui/index.js';
import type {
  BankAccountResponse,
  MatchSuggestionResponse,
  ReconcilableLineResponse,
  ReconciliationSummaryResponse,
} from '../lib/api-types.js';
import { errorMessage } from '../lib/errors.js';
import { money, parseMajorToMinorOrNull } from '../lib/money.js';

/**
 * Bank Reconciliation: tick off ledger entries on a bank account against the
 * statement. Enter the statement closing balance to see the difference between
 * the reconciled (cleared) balance and the statement — zero means it reconciles.
 */
export function ReconciliationScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [banks, setBanks] = useState<BankAccountResponse[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [lines, setLines] = useState<ReconcilableLineResponse[]>([]);
  const [summary, setSummary] = useState<ReconciliationSummaryResponse | null>(null);
  const [suggestions, setSuggestions] = useState<MatchSuggestionResponse[]>([]);
  const [statementInput, setStatementInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (companyId === null) {
      return;
    }
    api
      .listBankAccounts(companyId)
      .then((bs) => {
        setBanks(bs);
        const first = bs[0];
        if (first !== undefined) {
          setSelected(first.id);
        }
      })
      .catch(() => {
        /* non-fatal */
      });
  }, [api, companyId]);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null || selected === null) {
      setLines([]);
      setSummary(null);
      return;
    }
    setError(null);
    try {
      const stmt = parseMajorToMinorOrNull(statementInput);
      const [ls, sm] = await Promise.all([
        api.listReconcilableLines(companyId, selected),
        api.reconciliationSummary(companyId, selected, stmt),
      ]);
      setLines(ls);
      setSummary(sm);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load reconciliation.'));
    }
  }, [api, companyId, selected, statementInput]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggle(line: ReconcilableLineResponse): Promise<void> {
    if (companyId === null || selected === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.setLineReconciled(companyId, selected, line.journal_line_id, !line.reconciled);
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to update.'));
    } finally {
      setBusy(false);
    }
  }

  async function loadSuggestions(): Promise<void> {
    if (companyId === null || selected === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setSuggestions(await api.reconciliationSuggestions(companyId, selected));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load suggestions.'));
    } finally {
      setBusy(false);
    }
  }

  /** Accept a suggested match: reconcile the ledger entry it points at. */
  async function acceptSuggestion(s: MatchSuggestionResponse): Promise<void> {
    if (companyId === null || selected === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.setLineReconciled(companyId, selected, s.journal_line_id, true);
      setSuggestions((prev) => prev.filter((x) => x.journal_line_id !== s.journal_line_id));
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to accept the match.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  if (banks.length === 0) {
    return (
      <section aria-live="polite">
        <p>Create a bank account (Cashbook) first.</p>
      </section>
    );
  }

  return (
    <section aria-live="polite" className="recon-screen">
      <div className="recon-controls">
        <select
          value={selected ?? ''}
          onChange={(e) => {
            setSelected(e.target.value);
          }}
          aria-label="Bank account"
        >
          {banks.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <label>
          Statement closing balance{' '}
          <input
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            value={statementInput}
            onChange={(e) => {
              setStatementInput(e.target.value);
            }}
          />
        </label>
      </div>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {summary !== null && (
        <div className="recon-summary">
          <span>Ledger balance: {money(summary.ledger_balance_minor)}</span>
          <span>Reconciled: {money(summary.reconciled_balance_minor)}</span>
          <span>Outstanding items: {summary.unreconciled_count}</span>
          {summary.difference_minor !== null && (
            <span className={summary.difference_minor === 0 ? 'balanced' : 'unbalanced'}>
              Difference: {money(summary.difference_minor)}
              {summary.difference_minor === 0 ? ' (reconciled ✓)' : ''}
            </span>
          )}
        </div>
      )}

      <div className="recon-suggest-bar">
        <Button onClick={() => void loadSuggestions()} disabled={busy}>
          Suggest matches
        </Button>
      </div>

      {suggestions.length > 0 && (
        <table className="devices-table recon-suggestions">
          <thead>
            <tr>
              <th>Ledger entry</th>
              <th>Statement line</th>
              <th className="num">Amount</th>
              <th>Confidence</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {suggestions.map((s) => (
              <tr key={s.journal_line_id}>
                <td>
                  {s.ledger_date} · {s.ledger_narrative ?? '—'}
                </td>
                <td>
                  {s.statement_date ?? '—'} · {s.statement_description}
                </td>
                <td className="num">{money(s.amount_minor)}</td>
                <td>
                  <span className={`recon-conf recon-conf-${s.confidence}`}>
                    {s.confidence === 'exact'
                      ? 'Exact (same date)'
                      : s.days_apart !== null
                        ? `Amount (${String(s.days_apart)}d apart)`
                        : 'Amount'}
                  </span>
                </td>
                <td>
                  <Button disabled={busy} onClick={() => void acceptSuggestion(s)}>
                    Accept
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <table className="devices-table">
        <thead>
          <tr>
            <th>Reconciled</th>
            <th>Date</th>
            <th>Description</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {lines.length === 0 ? (
            <tr>
              <td colSpan={4}>No ledger entries on this bank account yet.</td>
            </tr>
          ) : (
            lines.map((line) => (
              <tr key={line.journal_line_id}>
                <td>
                  <input
                    type="checkbox"
                    checked={line.reconciled}
                    disabled={busy}
                    onChange={() => void toggle(line)}
                    aria-label={`Reconcile ${line.narrative ?? line.journal_line_id}`}
                  />
                </td>
                <td>{line.line_date ?? ''}</td>
                <td>{line.narrative ?? '—'}</td>
                <td className="num">{money(line.amount_minor)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
