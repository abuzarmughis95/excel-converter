import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

let finaliseCalled: Record<string, unknown> | null = null;
let submitted = false;
let hmrcConnected = false;
let hmrcSubmitBody: Record<string, unknown> | null = null;

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
    if (url.endsWith('/companies')) {
      return json(200, [{ id: 'co-1', name: 'Acme', base_currency: 'GBP', accounts_type: 'ltd', companies_house_no: null, vat_registration_no: null, role: 'owner' }]);
    }
    if (url.endsWith('/vat-return')) {
      return json(200, VAT);
    }
    if (url.endsWith('/vat-submissions') && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      finaliseCalled = body;
      submitted = true;
      return json(201, { id: 's-1', period_start: '2026-01-01', period_end: '2026-03-31', reference: String(body['reference']), finalised_at: '2026-04-01T00:00:00Z', boxes: VAT });
    }
    if (url.endsWith('/vat-submissions') && method === 'GET') {
      return json(200, submitted ? [{ id: 's-1', period_start: '2026-01-01', period_end: '2026-03-31', reference: 'HMRC-9', finalised_at: '2026-04-01T00:00:00Z', boxes: VAT }] : []);
    }
    if (url.endsWith('/hmrc/status')) {
      return json(200, { connected: hmrcConnected });
    }
    if (url.endsWith('/hmrc/submit') && method === 'POST') {
      hmrcSubmitBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return json(200, { submission_id: 's-1', form_bundle_number: 'BUNDLE-1', charge_ref_number: 'X1', received_at: '2026-04-07T12:00:00Z' });
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
  finaliseCalled = null;
  submitted = false;
  hmrcConnected = false;
  hmrcSubmitBody = null;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

  it('finalises the return with a reference and lock', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Finalise return')).toBeInTheDocument();
    });
    await user.type(screen.getByPlaceholderText('HMRC receipt'), 'HMRC-9');
    await user.click(screen.getByRole('button', { name: 'Finalise' }));

    await waitFor(() => {
      expect(finaliseCalled).toEqual({
        period_start: '2026-01-01',
        period_end: '2026-03-31',
        reference: 'HMRC-9',
        lock_period: true,
      });
    });
    // The submitted return now appears in the history.
    await waitFor(() => {
      expect(screen.getByText('Submitted returns')).toBeInTheDocument();
    });
  });

  it('submits a finalised return to HMRC when connected', async () => {
    const user = userEvent.setup();
    hmrcConnected = true;
    submitted = true; // a finalised return already exists in history
    vi.spyOn(window, 'prompt').mockReturnValue('18A1');
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    // Connected banner + a Submit to HMRC action on the finalised return.
    await waitFor(() => {
      expect(screen.getByText('Connected to HMRC ✓')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: 'Submit to HMRC' }));

    await waitFor(() => {
      expect(hmrcSubmitBody).toEqual({ submission_id: 's-1', period_key: '18A1' });
    });
    expect(screen.getByText(/Receipt: BUNDLE-1/)).toBeInTheDocument();
  });
});
