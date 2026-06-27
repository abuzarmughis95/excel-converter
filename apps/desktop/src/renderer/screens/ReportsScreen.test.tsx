import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { ReportsScreen } from './ReportsScreen.js';

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const PNL = {
  income: [{ account_code: '4000', account_name: 'Sales', amount_minor: 100000 }],
  expenses: [{ account_code: '5000', account_name: 'Costs', amount_minor: 30000 }],
  total_income_minor: 100000,
  total_expenses_minor: 30000,
  net_profit_minor: 70000,
};

const BS = {
  assets: [{ account_code: '1200', account_name: 'Bank', amount_minor: 120000 }],
  liabilities: [],
  equity: [{ account_code: '3000', account_name: 'Capital', amount_minor: 50000 }],
  total_assets_minor: 120000,
  total_liabilities_minor: 0,
  total_equity_minor: 120000,
  retained_earnings_minor: 70000,
};

function stubFetch(): void {
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = input instanceof URL ? input.href : String(input);
    if (url.endsWith('/auth/login')) {
      return json(200, { access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900, mfa_required: false });
    }
    if (url.endsWith('/auth/me')) {
      return json(200, { id: '00000000-0000-7000-8000-000000000000', email: 'u@example.com', display_name: 'U', status: 'active' });
    }
    if (url.endsWith('/companies')) {
      return json(200, [{ id: 'co-1', name: 'Acme', base_currency: 'GBP', accounts_type: 'ltd', companies_house_no: null, vat_registration_no: null, role: 'owner' }]);
    }
    if (url.endsWith('/profit-and-loss')) {
      return json(200, PNL);
    }
    if (url.endsWith('/balance-sheet')) {
      return json(200, BS);
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
      <ReportsScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ReportsScreen', () => {
  it('shows the P&L net profit, then the balance sheet on tab switch', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    // P&L tab is default.
    await waitFor(() => {
      expect(screen.getByText('Net profit')).toBeInTheDocument();
    });
    expect(screen.getByText('£700.00')).toBeInTheDocument();

    // Switch to Balance Sheet.
    await user.click(screen.getByRole('button', { name: 'Balance Sheet' }));
    await waitFor(() => {
      expect(screen.getByText('Total assets')).toBeInTheDocument();
    });
    // £1200.00 appears on several rows (bank, total assets, total equity, L+E).
    expect(screen.getAllByText('£1200.00').length).toBeGreaterThan(0);
    expect(screen.getByText('Liabilities + Equity')).toBeInTheDocument();
  });
});
