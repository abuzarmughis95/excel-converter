import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { JournalEntryScreen } from './JournalEntryScreen.js';

let unpostCalled: { id: string; reason: string } | null = null;
let posted = true;

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const JOURNAL = {
  id: 'j-1',
  journal_date: '2026-06-27',
  journal_type: 'journal',
  reference: null,
  narrative: 'Test sale',
  currency: 'GBP',
  is_posted: true,
  lines: [],
};

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
      return json(200, [{ id: 'a-1', code: '1200', name: 'Bank', account_type: 'asset', normal_balance: 'DR', is_active: true }]);
    }
    if (url.endsWith('/journals') && method === 'GET') {
      return json(200, [{ ...JOURNAL, is_posted: posted }]);
    }
    if (url.endsWith('/trial-balance') && method === 'GET') {
      return json(200, []);
    }
    if (url.includes('/journals/j-1/unpost') && method === 'POST') {
      unpostCalled = { id: 'j-1', reason: (JSON.parse(String(init?.body)) as { reason: string }).reason };
      posted = false;
      return json(200, { ...JOURNAL, is_posted: false });
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
      <JournalEntryScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  unpostCalled = null;
  posted = true;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('JournalEntryScreen corrections', () => {
  it('unposts a posted journal with a reason', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'prompt').mockReturnValue('entered in error');
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Test sale/)).toBeInTheDocument();
    });
    // A posted journal shows Unpost and Reverse actions.
    expect(screen.getByRole('button', { name: 'Reverse' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Unpost' }));

    await waitFor(() => {
      expect(unpostCalled).toEqual({ id: 'j-1', reason: 'entered in error' });
    });
  });
});
