import { useEffect, useRef, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button } from '../components/ui/index.js';
import { ApiError } from '../lib/api-client.js';
import { errorMessage } from '../lib/errors.js';
import type { BankAccountResponse, ExtractStatementResponse } from '../lib/api-types.js';
import { formatMinorPlain as formatMinor } from '../lib/money.js';

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
  const [banks, setBanks] = useState<BankAccountResponse[]>([]);
  const [importBank, setImportBank] = useState('');
  const [importMsg, setImportMsg] = useState<string | null>(null);

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
          setImportBank(first.id);
        }
      })
      .catch(() => {
        /* non-fatal; import section simply hidden */
      });
  }, [api, companyId]);

  async function onImport(): Promise<void> {
    if (companyId === null || result === null || importBank === '') {
      return;
    }
    setBusy(true);
    setImportMsg(null);
    setError(null);
    try {
      const res = await api.importStatementLines(
        companyId,
        importBank,
        result.lines.map((ln) => ({
          line_date: ln.date,
          description: ln.description,
          money_out_minor: ln.money_out_minor,
          money_in_minor: ln.money_in_minor,
          balance_minor: ln.balance_minor,
        })),
      );
      setImportMsg(
        `Imported ${String(res.imported)} lines` +
          (res.duplicates > 0 ? ` (${String(res.duplicates)} duplicates skipped)` : '') +
          '. Post them to the ledger in Cashbook.',
      );
    } catch (err) {
      setError(errorMessage(err, 'Failed to import lines.'));
    } finally {
      setBusy(false);
    }
  }

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
        setError(errorMessage(err, 'Failed to extract the statement.'));
      }
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
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
        <Button
          onClick={() => {
            fileInput.current?.click();
          }}
          disabled={busy}
        >
          {busy ? 'Extracting…' : 'Upload bank statement (PDF)'}
        </Button>
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

          {result.lines.length > 0 && (
            <div className="statements-import">
              {banks.length === 0 ? (
                <p>Create a bank account (Cashbook) to import these lines.</p>
              ) : (
                <>
                  <select
                    value={importBank}
                    onChange={(e) => {
                      setImportBank(e.target.value);
                    }}
                    aria-label="Import into bank account"
                  >
                    {banks.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                  <Button onClick={() => void onImport()} disabled={busy}>
                    Import {result.lines.length} lines to cashbook
                  </Button>
                </>
              )}
              {importMsg !== null && (
                <p className="balanced" role="status">
                  {importMsg}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
