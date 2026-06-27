import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { ChartOfAccountsScreen } from './ChartOfAccountsScreen.js';

let accounts: Record<string, unknown>[] = [];

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

function stubFetch(): void {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = input instanceof URL ? input.href : String(input);
    const method = init?.method ?? 'GET';
    if (url.endsWith('/auth/login')) {
      return json(200, {
        access_token: 'a',
        refresh_token: 'r',
        token_type: 'bearer',
        expires_in: 900,
        mfa_required: false,
      });
    }
    if (url.endsWith('/auth/me')) {
      return json(200, {
        id: '00000000-0000-7000-8000-000000000000',
        email: 'u@example.com',
        display_name: 'U',
        status: 'active',
      });
    }
    if (url.endsWith('/companies') && method === 'GET') {
      return json(200, [
        {
          id: 'co-1',
          name: 'Acme',
          base_currency: 'GBP',
          accounts_type: 'ltd',
          companies_house_no: null,
          vat_registration_no: null,
          role: 'owner',
        },
      ]);
    }
    if (url.endsWith('/accounts') && method === 'GET') {
      return json(200, accounts);
    }
    if (url.endsWith('/accounts') && method === 'POST') {
      const created = {
        id: 'acc-1',
        code: '1200',
        name: 'Bank',
        account_type: 'asset',
        normal_balance: 'DR',
        is_control: false,
        control_kind: null,
        is_active: true,
      };
      accounts = [created];
      return json(201, created);
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
      <ChartOfAccountsScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  accounts = [];
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ChartOfAccountsScreen', () => {
  it('shows empty state then creates an account with engine-derived normal balance', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/No accounts yet/i)).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('Code (e.g. 1200)'), '1200');
    await user.type(screen.getByPlaceholderText('Account name'), 'Bank');
    await user.click(screen.getByRole('button', { name: /Add account/i }));

    await waitFor(() => {
      expect(screen.getByText('Bank')).toBeInTheDocument();
    });
    // Normal balance DR comes from the backend engine.
    expect(screen.getByText('DR')).toBeInTheDocument();
  });
});
