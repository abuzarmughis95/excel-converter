import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { PeriodsScreen } from './PeriodsScreen.js';

let periodStatus: 'open' | 'soft_closed' | 'locked' = 'open';

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
      return json(200, { access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900, mfa_required: false });
    }
    if (url.endsWith('/auth/me')) {
      return json(200, { id: '00000000-0000-7000-8000-000000000000', email: 'u@example.com', display_name: 'U', status: 'active' });
    }
    if (url.endsWith('/companies') && method === 'GET') {
      return json(200, [{ id: 'co-1', name: 'Acme', base_currency: 'GBP', accounts_type: 'ltd', companies_house_no: null, vat_registration_no: null, role: 'owner' }]);
    }
    if (url.endsWith('/periods') && method === 'GET') {
      return json(200, [
        { id: 'p-1', fiscal_year: 2026, starts_on: '2026-01-01', ends_on: '2026-12-31', status: periodStatus },
      ]);
    }
    if (url.includes('/periods/p-1/status') && method === 'POST') {
      periodStatus = (JSON.parse(String(init?.body)) as { status: typeof periodStatus }).status;
      return json(200, { id: 'p-1', fiscal_year: 2026, starts_on: '2026-01-01', ends_on: '2026-12-31', status: periodStatus });
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
      <PeriodsScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  periodStatus = 'open';
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PeriodsScreen', () => {
  it('lists a period and soft-closes it', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('2026')).toBeInTheDocument();
    });
    expect(screen.getByText('Open')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Soft-close' }));

    await waitFor(() => {
      expect(screen.getByText('Soft-closed')).toBeInTheDocument();
    });
    // Once soft-closed, a Reopen and a Lock action are offered.
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lock' })).toBeInTheDocument();
  });
});
