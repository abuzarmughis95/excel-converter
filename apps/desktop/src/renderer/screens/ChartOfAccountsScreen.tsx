import { useCallback, useEffect, useState, type FormEvent, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button } from '../components/ui/index.js';
import type { AccountResponse } from '../lib/api-types.js';
import { errorMessage } from '../lib/errors.js';

const ACCOUNT_TYPES = ['asset', 'liability', 'equity', 'income', 'expense'] as const;

/**
 * Chart of Accounts screen for the active company: lists accounts and lets the
 * user add one. The normal balance (DR/CR) is computed by the backend's
 * accounting engine, so it appears as soon as an account is created.
 */
export function ChartOfAccountsScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [accountType, setAccountType] = useState<string>('asset');
  const [busy, setBusy] = useState(false);

  const companyId = activeCompany?.id ?? null;

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      setAccounts([]);
      setLoading(false);
      return;
    }
    setError(null);
    try {
      setAccounts(await api.listAccounts(companyId));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load accounts.'));
    } finally {
      setLoading(false);
    }
  }, [api, companyId]);

  useEffect(() => {
    setLoading(true);
    void reload();
  }, [reload]);

  async function onCreate(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createAccount(companyId, { code, name, account_type: accountType });
      setCode('');
      setName('');
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create account.'));
    } finally {
      setBusy(false);
    }
  }

  async function onDeactivate(accountId: string): Promise<void> {
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deactivateAccount(companyId, accountId);
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to deactivate account.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  return (
    <section aria-live="polite">
      <form
        className="company-create"
        onSubmit={(e) => {
          void onCreate(e);
        }}
        aria-label="Add account"
      >
        <input
          type="text"
          placeholder="Code (e.g. 1200)"
          value={code}
          required
          onChange={(e) => {
            setCode(e.target.value);
          }}
          style={{ maxWidth: 140 }}
        />
        <input
          type="text"
          placeholder="Account name"
          value={name}
          required
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <select
          value={accountType}
          onChange={(e) => {
            setAccountType(e.target.value);
          }}
          aria-label="Account type"
        >
          {ACCOUNT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={busy}>
          Add account
        </Button>
      </form>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p>Loading accounts…</p>
      ) : accounts.length === 0 ? (
        <p>No accounts yet. Add one above to start building the chart of accounts.</p>
      ) : (
        <table className="devices-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>Normal</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id} style={{ opacity: a.is_active ? 1 : 0.5 }}>
                <td>{a.code}</td>
                <td>{a.name}</td>
                <td>{a.account_type}</td>
                <td>{a.normal_balance}</td>
                <td>{a.is_active ? 'Active' : 'Inactive'}</td>
                <td>
                  {a.is_active && (
                    <Button
                      variant="danger"
                      onClick={() => void onDeactivate(a.id)}
                      disabled={busy}
                    >
                      Deactivate
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
