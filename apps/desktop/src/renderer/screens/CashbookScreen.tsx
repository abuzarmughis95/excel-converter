import { useCallback, useEffect, useState, type FormEvent, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { errorMessage } from '../lib/errors.js';
import type {
  AccountResponse,
  BankAccountResponse,
  BankStatementLineResponse,
} from '../lib/api-types.js';
import { formatMinorPlain } from '../lib/money.js';

function formatMinor(minor: number | null): string {
  return formatMinorPlain(minor, { blankZero: true });
}

/**
 * Cashbook: manage bank accounts and post imported statement lines to the
 * ledger. Selecting a bank account lists its statement lines; each unposted line
 * can be posted against a chosen contra account, which creates a balanced
 * journal (validated by the engine) that flows into the trial balance.
 */
export function CashbookScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [banks, setBanks] = useState<BankAccountResponse[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [lines, setLines] = useState<BankStatementLineResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // New bank account form.
  const [newName, setNewName] = useState('');
  const [newGl, setNewGl] = useState('');
  // Per-line contra selection.
  const [contra, setContra] = useState<Record<string, string>>({});

  const reloadBanks = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [accs, bs] = await Promise.all([
        api.listAccounts(companyId),
        api.listBankAccounts(companyId),
      ]);
      setAccounts(accs.filter((a) => a.is_active));
      setBanks(bs);
      const first = bs[0];
      if (selected === null && first !== undefined) {
        setSelected(first.id);
      }
    } catch (err) {
      setError(errorMessage(err, 'Failed to load.'));
    }
  }, [api, companyId, selected]);

  const reloadLines = useCallback(async (): Promise<void> => {
    if (companyId === null || selected === null) {
      setLines([]);
      return;
    }
    try {
      setLines(await api.listStatementLines(companyId, selected));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load lines.'));
    }
  }, [api, companyId, selected]);

  useEffect(() => {
    void reloadBanks();
  }, [reloadBanks]);

  useEffect(() => {
    void reloadLines();
  }, [reloadLines]);

  async function onCreateBank(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.createBankAccount(companyId, {
        name: newName,
        gl_account_id: newGl,
      });
      setNewName('');
      setNewGl('');
      await reloadBanks();
      setSelected(created.id);
    } catch (err) {
      setError(errorMessage(err, 'Failed to create bank account.'));
    } finally {
      setBusy(false);
    }
  }

  async function onPost(lineId: string): Promise<void> {
    if (companyId === null || selected === null) {
      return;
    }
    const contraId = contra[lineId];
    if (contraId === undefined || contraId === '') {
      setError('Pick a contra account for this line first.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.postStatementLine(companyId, selected, lineId, contraId);
      await reloadLines();
    } catch (err) {
      setError(errorMessage(err, 'Failed to post line.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  return (
    <section aria-live="polite" className="cashbook-screen">
      <form className="company-create" onSubmit={(e) => void onCreateBank(e)} aria-label="Add bank account">
        <input
          type="text"
          placeholder="Bank account name"
          value={newName}
          required
          onChange={(e) => {
            setNewName(e.target.value);
          }}
        />
        <select value={newGl} onChange={(e) => { setNewGl(e.target.value); }} required aria-label="GL account">
          <option value="">— GL bank account —</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} · {a.name}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy || accounts.length === 0}>
          Add bank account
        </button>
      </form>

      {accounts.length === 0 && (
        <p>Add a chart-of-accounts bank account (Bookkeeping) first.</p>
      )}

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {banks.length > 0 && (
        <div className="cashbook-banks">
          {banks.map((b) => (
            <button
              key={b.id}
              type="button"
              className={b.id === selected ? 'cashbook-bank active' : 'cashbook-bank'}
              onClick={() => {
                setSelected(b.id);
              }}
            >
              {b.name}
            </button>
          ))}
        </div>
      )}

      {selected !== null && (
        <table className="devices-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Description</th>
              <th className="num">Out</th>
              <th className="num">In</th>
              <th>Post to</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 ? (
              <tr>
                <td colSpan={6}>No statement lines. Import some from Bank Statements.</td>
              </tr>
            ) : (
              lines.map((ln) => (
                <tr key={ln.id} style={{ opacity: ln.is_posted ? 0.55 : 1 }}>
                  <td>{ln.line_date ?? ''}</td>
                  <td>{ln.description}</td>
                  <td className="num">{formatMinor(ln.money_out_minor)}</td>
                  <td className="num">{formatMinor(ln.money_in_minor)}</td>
                  <td>
                    {ln.is_posted ? (
                      <span className="balanced">Posted</span>
                    ) : (
                      <select
                        value={contra[ln.id] ?? ''}
                        onChange={(e) => {
                          setContra((prev) => ({ ...prev, [ln.id]: e.target.value }));
                        }}
                        aria-label={`Contra account for ${ln.description}`}
                      >
                        <option value="">— account —</option>
                        {accounts.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.code} · {a.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td>
                    {!ln.is_posted && (
                      <button type="button" onClick={() => void onPost(ln.id)} disabled={busy}>
                        Post
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}
