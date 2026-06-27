import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { ReconciliationScreen } from './ReconciliationScreen.js';

let lineReconciled = false;

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

function stubFetch(): void {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = input instanceof URL ? input.href : String(input);
    const method = init?.method ?? 'GET';
    if (url.endsWith('/auth/login')) {
      return json(200, { access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900, mfa_required: false });
    }
    if (url.endsWith('/auth/me')) {
      return json(200, { id: '00000000-0000-7000-8000-000000000000', email: 'u@example.com', display_name: 'U', status: 'active' });
    }
    if (url.endsWith('/companies') && method === 'GET') {
      return json(200, [{ id: 'co-1', name: 'Acme', base_currency: 'GBP', accounts_type: 'ltd', companies_house_no: null, vat_registration_no: null, role: 'owner' }]);
    }
    if (url.endsWith('/bank-accounts') && method === 'GET') {
      return json(200, [{ id: 'bank-1', name: 'Current', gl_account_id: 'gl-1', account_number: null, sort_code: null, currency: 'GBP' }]);
    }
    if (url.endsWith('/reconciliation') && method === 'GET') {
      return json(200, [
        { journal_line_id: 'jl-1', journal_id: 'j-1', line_date: '2026-06-27', narrative: 'SALE A', amount_minor: 10000, reconciled: lineReconciled },
      ]);
    }
    if (url.includes('/reconciliation/') && method === 'POST') {
      lineReconciled = (JSON.parse(String(init?.body)) as { reconciled: boolean }).reconciled;
      return json(204, null);
    }
    if (url.includes('/reconciliation-suggestions')) {
      return json(200, lineReconciled ? [] : [
        {
          journal_line_id: 'jl-1',
          ledger_date: '2026-06-27',
          ledger_narrative: 'SALE A',
          statement_line_id: 'sl-1',
          statement_date: '2026-06-27',
          statement_description: 'SALE A',
          amount_minor: 10000,
          confidence: 'exact',
          days_apart: 0,
        },
      ]);
    }
    if (url.includes('/reconciliation-summary')) {
      return json(200, {
        ledger_balance_minor: 10000,
        reconciled_balance_minor: lineReconciled ? 10000 : 0,
        unreconciled_count: lineReconciled ? 0 : 1,
        statement_balance_minor: null,
        difference_minor: null,
      });
    }
    return json(404, { detail: 'not found' });
  });
  vi.stubGlobal('fetch', fetchMock);
}

function PreAuth(): JSX.Element {
  const { isAuthenticated, login } = useAuth();
  useEffect(() => {
    if (!isAuthenticated) {
      void login('u@example.com', 'password123');
    }
  }, [isAuthenticated, login]);
  if (!isAuthenticated) {
    return <p>signing in…</p>;
  }
  return (
    <CompanyProvider>
      <ReconciliationScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  lineReconciled = false;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ReconciliationScreen', () => {
  it('lists ledger entries and reconciles one', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('SALE A')).toBeInTheDocument();
    });
    const checkbox = screen.getByLabelText('Reconcile SALE A');
    expect(checkbox).not.toBeChecked();

    await user.click(checkbox);

    await waitFor(() => {
      expect(screen.getByLabelText('Reconcile SALE A')).toBeChecked();
    });
    expect(screen.getByText('Outstanding items: 0')).toBeInTheDocument();
  });

  it('suggests a match and accepts it', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('SALE A')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Suggest matches' }));

    // The exact-confidence suggestion appears with an Accept action.
    await waitFor(() => {
      expect(screen.getByText('Exact (same date)')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: 'Accept' }));

    // Accepting reconciles the ledger entry.
    await waitFor(() => {
      expect(screen.getByLabelText('Reconcile SALE A')).toBeChecked();
    });
  });
});
