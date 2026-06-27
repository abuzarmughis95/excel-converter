import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { CompaniesScreen } from './CompaniesScreen.js';

let companies: Record<string, unknown>[] = [];

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
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
      return jsonResponse(200, {
        access_token: 'a',
        refresh_token: 'r',
        token_type: 'bearer',
        expires_in: 900,
        mfa_required: false,
      });
    }
    if (url.endsWith('/auth/me')) {
      return jsonResponse(200, {
        id: '00000000-0000-7000-8000-000000000000',
        email: 'u@example.com',
        display_name: 'U',
        status: 'active',
      });
    }
    if (url.endsWith('/companies') && method === 'GET') {
      return jsonResponse(200, companies);
    }
    if (url.endsWith('/companies') && method === 'POST') {
      const created = {
        id: 'company-1',
        name: 'Acme Ltd',
        base_currency: 'GBP',
        accounts_type: 'ltd',
        companies_house_no: null,
        vat_registration_no: null,
        role: 'owner',
      };
      companies = [created];
      return jsonResponse(201, created);
    }
    return jsonResponse(404, { detail: 'not found' });
  });
  vi.stubGlobal('fetch', fetchMock);
}

/** Renders the screen inside the auth + company providers, pre-authenticated. */
function renderScreen(): void {
  render(
    <AuthProvider>
      <PreAuth />
    </AuthProvider>,
  );
}

// Helper component: signs in then renders the companies screen.
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
      <CompaniesScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  companies = [];
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CompaniesScreen', () => {
  it('shows an empty state then creates a company', async () => {
    const user = userEvent.setup();
    renderScreen();

    await waitFor(() => {
      expect(screen.getByText(/No companies yet/i)).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText('New company name'), 'Acme Ltd');
    await user.click(screen.getByRole('button', { name: /Create company/i }));

    await waitFor(() => {
      expect(screen.getByText('Acme Ltd')).toBeInTheDocument();
    });
    // The newly created company becomes active.
    expect(screen.getByRole('button', { name: /Acme Ltd/ })).toHaveAttribute('aria-current', 'true');
  });
});
