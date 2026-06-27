import { useState, type FormEvent, type JSX } from 'react';

import { useCompanies } from '../company/CompanyContext.js';
import { errorMessage } from '../lib/errors.js';

const ACCOUNTS_TYPES = ['sole_trader', 'partnership', 'ltd', 'micro', 'small'] as const;

/**
 * Companies screen: lists the user's companies, lets them select an active one,
 * and create a new company — all wired to the live backend.
 */
export function CompaniesScreen(): JSX.Element {
  const { companies, activeCompany, loading, selectCompany, createCompany } = useCompanies();
  const [name, setName] = useState('');
  const [accountsType, setAccountsType] = useState<string>('ltd');
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  async function onCreate(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      await createCompany({ name, accounts_type: accountsType });
      setName('');
    } catch (err) {
      setError(errorMessage(err, 'Failed to create company.'));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section aria-live="polite" className="companies-screen">
      <form
        className="company-create"
        onSubmit={(e) => {
          void onCreate(e);
        }}
        aria-label="Create company"
      >
        <input
          type="text"
          placeholder="New company name"
          value={name}
          required
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <select
          value={accountsType}
          onChange={(e) => {
            setAccountsType(e.target.value);
          }}
          aria-label="Accounts type"
        >
          {ACCOUNTS_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button type="submit" disabled={creating}>
          {creating ? 'Creating…' : 'Create company'}
        </button>
      </form>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p>Loading companies…</p>
      ) : companies.length === 0 ? (
        <p>No companies yet. Create one above to get started.</p>
      ) : (
        <ul className="company-list">
          {companies.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={c.id === activeCompany?.id ? 'company-item active' : 'company-item'}
                onClick={() => {
                  selectCompany(c.id);
                }}
                aria-current={c.id === activeCompany?.id ? 'true' : undefined}
              >
                <span className="company-name">{c.name}</span>
                <span className="company-meta">
                  {c.accounts_type} · {c.base_currency} · {c.role}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
