import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { CashbookScreen } from './CashbookScreen.js';

let lines: Record<string, unknown>[] = [];
let postedContra: string | null = null;

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const ACCOUNTS = [
  { id: 'acc-bank', code: '1200', name: 'Bank', account_type: 'asset', normal_balance: 'DR', is_control: false, control_kind: null, is_active: true },
  { id: 'acc-sales', code: '4000', name: 'Sales', account_type: 'income', normal_balance: 'CR', is_control: false, control_kind: null, is_active: true },
];

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
    if (url.endsWith('/accounts') && method === 'GET') {
      return json(200, ACCOUNTS);
    }
    if (url.endsWith('/bank-accounts') && method === 'GET') {
      return json(200, [{ id: 'bank-1', name: 'Current', gl_account_id: 'acc-bank', account_number: null, sort_code: null, currency: 'GBP' }]);
    }
    if (url.endsWith('/lines') && method === 'GET') {
      return json(200, lines);
    }
    if (url.includes('/lines/') && url.endsWith('/post') && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as { contra_account_id: string };
      postedContra = body.contra_account_id;
      lines = lines.map((l) => ({ ...l, is_posted: true }));
      return json(200, { journal_id: 'j-1' });
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
      <CashbookScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  postedContra = null;
  lines = [
    { id: 'line-1', line_date: '2026-06-27', description: 'SALES RECEIPT', money_out_minor: 0, money_in_minor: 20000, balance_minor: null, is_posted: false },
  ];
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CashbookScreen', () => {
  it('posts a statement line against a chosen contra account', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('SALES RECEIPT')).toBeInTheDocument();
    });

    // Choose the contra account (Sales) and post.
    const contraSelect = screen.getByLabelText('Contra account for SALES RECEIPT');
    await user.selectOptions(contraSelect, 'acc-sales');
    await user.click(screen.getByRole('button', { name: 'Post' }));

    await waitFor(() => {
      expect(screen.getByText('Posted')).toBeInTheDocument();
    });
    expect(postedContra).toBe('acc-sales');
  });
});
