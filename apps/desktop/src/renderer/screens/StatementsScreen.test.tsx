import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { StatementsScreen } from './StatementsScreen.js';

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const EXTRACTED = {
  currency: 'GBP',
  reconciled: true,
  summary: {
    account_name: 'ACME LTD',
    account_number: '12345678',
    sort_code: '12-34-56',
    period_start: '2026-06-01',
    period_end: '2026-06-30',
    opening_balance_minor: 100000,
    closing_balance_minor: 115000,
  },
  lines: [
    { date: '2026-06-02', description: 'CARD PAYMENT', money_out_minor: 5000, money_in_minor: 0, balance_minor: 95000 },
    { date: '2026-06-10', description: 'SALES', money_out_minor: 0, money_in_minor: 20000, balance_minor: 115000 },
  ],
};

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
    if (url.endsWith('/statements/extract') && method === 'POST') {
      return json(200, EXTRACTED);
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
      <StatementsScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('StatementsScreen', () => {
  it('uploads a PDF and shows the extracted summary and lines', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Upload bank statement/i }),
      ).toBeInTheDocument();
    });

    const file = new File([new Uint8Array([1, 2, 3])], 'statement.pdf', {
      type: 'application/pdf',
    });
    // The hidden file input is associated with the upload button.
    const input = document.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input as HTMLInputElement, file);

    await waitFor(() => {
      expect(screen.getByText('Reconciled ✓')).toBeInTheDocument();
    });
    expect(screen.getByText('CARD PAYMENT')).toBeInTheDocument();
    expect(screen.getByText('2 transactions extracted.')).toBeInTheDocument();
  });
});
