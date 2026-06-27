import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { FixedAssetsScreen } from './FixedAssetsScreen.js';

let depreciated = false;

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

function asset(): unknown {
  return {
    id: 'a-1',
    name: 'Laptop',
    category: null,
    acquired_on: '2026-01-01',
    cost_minor: 120000,
    residual_minor: 0,
    method: 'straight_line',
    useful_life_periods: 12,
    rate_percent: null,
    accumulated_depreciation_minor: depreciated ? 10000 : 0,
    net_book_value_minor: depreciated ? 110000 : 120000,
    periods_depreciated: depreciated ? 1 : 0,
    disposed: false,
  };
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
    if (url.endsWith('/accounts') && method === 'GET') {
      return json(200, [
        { id: 'acc-1', code: '0100', name: 'Equipment', account_type: 'asset', normal_balance: 'DR', is_active: true },
      ]);
    }
    if (url.endsWith('/fixed-assets') && method === 'GET') {
      return json(200, [asset()]);
    }
    if (url.includes('/fixed-assets/a-1/depreciate') && method === 'POST') {
      depreciated = true;
      return json(200, { asset_id: 'a-1', charge_minor: 10000, journal_id: 'j-1' });
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
      <FixedAssetsScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  depreciated = false;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FixedAssetsScreen', () => {
  it('shows the register with net book value and depreciates an asset', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Laptop')).toBeInTheDocument();
    });
    // Initial cost + NBV both 1200.00 (two cells).
    expect(screen.getAllByText('£1200.00').length).toBe(2);

    await user.click(screen.getByRole('button', { name: 'Depreciate' }));

    // After depreciation, the charge is reported and NBV drops to 1100.00.
    await waitFor(() => {
      expect(screen.getByText('£1100.00')).toBeInTheDocument();
    });
    expect(screen.getByText(/Charged £100.00 depreciation/)).toBeInTheDocument();
  });
});
