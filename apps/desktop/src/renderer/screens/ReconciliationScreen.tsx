import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { ApiError } from '../lib/api-client.js';
import type {
  BankAccountResponse,
  ReconcilableLineResponse,
  ReconciliationSummaryResponse,
} from '../lib/api-types.js';

function money(minor: number): string {
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  return `£${sign}${Math.trunc(abs / 100).toString()}.${(abs % 100).toString().padStart(2, '0')}`;
}

/** Parse a "1234.56" statement balance into integer minor units (or null). */
function parseBalance(input: string): number | null {
  const cleaned = input.trim().replace(/[,£\s]/g, '');
  if (cleaned === '') {
    return null;
  }
  if (!/^-?\d+(\.\d{1,2})?$/.test(cleaned)) {
    return null;
  }
  const negative = cleaned.startsWith('-');
  const unsigned = negative ? cleaned.slice(1) : cleaned;
  const [whole, frac = ''] = unsigned.split('.');
  const minor = Number(whole) * 100 + Number(frac.padEnd(2, '0'));
  return negative ? -minor : minor;
}

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
      const stmt = parseBalance(statementInput);
      const [ls, sm] = await Promise.all([
        api.listReconcilableLines(companyId, selected),
        api.reconciliationSummary(companyId, selected, stmt),
      ]);
      setLines(ls);
      setSummary(sm);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load reconciliation.');
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
      setError(err instanceof ApiError ? err.message : 'Failed to update.');
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return (
      <section aria-live="polite">
        <p>Select or create a company first (Companies screen).</p>
      </section>
    );
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
