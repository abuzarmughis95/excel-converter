import { useRef, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { ApiError } from '../lib/api-client.js';
import type { ExtractStatementResponse } from '../lib/api-types.js';

function formatMinor(minor: number | null): string {
  if (minor === null) {
    return '';
  }
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  const whole = Math.trunc(abs / 100).toString();
  const frac = (abs % 100).toString().padStart(2, '0');
  return `${sign}${whole}.${frac}`;
}

/**
 * Bank Statements screen: upload a statement PDF, which is sent to the backend
 * for AI extraction (OpenAI vision). Shows the account summary, a reconciliation
 * indicator, and the extracted transaction lines.
 */
export function StatementsScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const fileInput = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<ExtractStatementResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  async function onFile(file: File): Promise<void> {
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    setFileName(file.name);
    try {
      setResult(await api.extractStatement(companyId, file));
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError('Statement extraction is not configured on the server (no API key).');
      } else {
        setError(err instanceof ApiError ? err.message : 'Failed to extract the statement.');
      }
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

  return (
    <section aria-live="polite" className="statements-screen">
      <div className="statements-upload">
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f !== undefined) {
              void onFile(f);
            }
          }}
        />
        <button
          type="button"
          onClick={() => {
            fileInput.current?.click();
          }}
          disabled={busy}
        >
          {busy ? 'Extracting…' : 'Upload bank statement (PDF)'}
        </button>
        {fileName !== null && <span className="statements-filename">{fileName}</span>}
      </div>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {result !== null && (
        <>
          <div className="statements-summary">
            <h3>
              Account summary{' '}
              {result.reconciled ? (
                <span className="balanced">Reconciled ✓</span>
              ) : (
                <span className="unbalanced">Not reconciled — please review</span>
              )}
            </h3>
            <dl>
              <div>
                <dt>Account</dt>
                <dd>
                  {result.summary.account_name ?? '—'}{' '}
                  {result.summary.account_number !== null && `· ${result.summary.account_number}`}{' '}
                  {result.summary.sort_code !== null && `· ${result.summary.sort_code}`}
                </dd>
              </div>
              <div>
                <dt>Period</dt>
                <dd>
                  {result.summary.period_start ?? '?'} → {result.summary.period_end ?? '?'}
                </dd>
              </div>
              <div>
                <dt>Opening</dt>
                <dd>{formatMinor(result.summary.opening_balance_minor)}</dd>
              </div>
              <div>
                <dt>Closing</dt>
                <dd>{formatMinor(result.summary.closing_balance_minor)}</dd>
              </div>
            </dl>
          </div>

          <table className="devices-table statements-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th className="num">Out</th>
                <th className="num">In</th>
                <th className="num">Balance</th>
              </tr>
            </thead>
            <tbody>
              {result.lines.map((ln, i) => (
                <tr key={i}>
                  <td>{ln.date ?? ''}</td>
                  <td>{ln.description}</td>
                  <td className="num">{ln.money_out_minor ? formatMinor(ln.money_out_minor) : ''}</td>
                  <td className="num">{ln.money_in_minor ? formatMinor(ln.money_in_minor) : ''}</td>
                  <td className="num">{formatMinor(ln.balance_minor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="statements-count">{result.lines.length} transactions extracted.</p>
        </>
      )}
    </section>
  );
}
