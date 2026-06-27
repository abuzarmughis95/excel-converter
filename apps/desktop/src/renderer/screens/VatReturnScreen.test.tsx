import { render, screen, waitFor } from '@testing-library/react';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { VatReturnScreen } from './VatReturnScreen.js';

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const VAT = {
  box1_minor: 20000,
  box2_minor: 0,
  box3_minor: 20000,
  box4_minor: 10000,
  box5_minor: 10000,
  box6_minor: 100000,
  box7_minor: 50000,
  box8_minor: 0,
  box9_minor: 0,
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
    if (url.endsWith('/vat-return')) {
      return json(200, VAT);
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
      <VatReturnScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('VatReturnScreen', () => {
  it('shows the 9 boxes and the net payable conclusion', async () => {
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Box 1')).toBeInTheDocument();
    });
    expect(screen.getByText('Box 9')).toBeInTheDocument();
    // Box 6 sales ex VAT 1000.00 is unique; output VAT (200.00) appears in
    // boxes 1 and 3, so assert via getAllByText instead.
    expect(screen.getByText('£1000.00')).toBeInTheDocument();
    expect(screen.getAllByText('£200.00').length).toBeGreaterThan(0);
    expect(screen.getByText('£100.00 payable to HMRC.')).toBeInTheDocument();
  });
});
