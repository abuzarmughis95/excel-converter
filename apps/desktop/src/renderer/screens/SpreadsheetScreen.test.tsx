import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { SpreadsheetScreen } from './SpreadsheetScreen.js';

let savedBody: unknown = null;

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
    if (url.endsWith('/workbook') && method === 'GET') {
      return json(200, {
        id: 'wb-1',
        name: 'Workbook',
        sheets: [{ name: 'Sheet1', sort_order: 0, cells: [] }],
      });
    }
    if (url.endsWith('/workbook') && method === 'PUT') {
      savedBody = init?.body !== undefined ? JSON.parse(String(init.body)) : null;
      return json(200, {
        id: 'wb-1',
        name: 'Workbook',
        sheets: [{ name: 'Sheet1', sort_order: 0, cells: [['hello']] }],
      });
    }
    if (url.endsWith('/statements/extract') && method === 'POST') {
      return json(200, {
        currency: 'GBP',
        reconciled: true,
        summary: {
          account_name: 'ACME', account_number: '1', sort_code: '1', period_start: null,
          period_end: null, opening_balance_minor: 0, closing_balance_minor: 0,
        },
        lines: [
          { date: '2026-06-27', description: 'CARD PAYMENT', money_out_minor: 5000, money_in_minor: 0, balance_minor: 95000 },
        ],
      });
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
      <SpreadsheetScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  savedBody = null;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SpreadsheetScreen', () => {
  it('loads a sheet, edits a cell, and saves with Ctrl+S', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    // The default sheet tab loads.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sheet1' })).toBeInTheDocument();
    });

    // Type into cell A1.
    const a1 = screen.getByLabelText('A1');
    await user.type(a1, 'hello');
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();

    // Ctrl+S saves.
    fireEvent.keyDown(window, { key: 's', ctrlKey: true });

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });
    // The saved payload contains the edited cell.
    expect(JSON.stringify(savedBody)).toContain('hello');
  });

  it('adds a new sheet tab', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sheet1' })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Add sheet' }));
    expect(screen.getByRole('button', { name: 'Sheet2' })).toBeInTheDocument();
  });

  it('imports a PDF into a new sheet with the extracted rows', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sheet1' })).toBeInTheDocument();
    });

    const file = new File([new Uint8Array([1, 2, 3])], 'june-statement.pdf', {
      type: 'application/pdf',
    });
    const input = document.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(input as HTMLInputElement, file);

    // A new tab named after the file appears, becomes active, and the extracted
    // transaction lands in the grid.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'june-statement' })).toBeInTheDocument();
    });
    const cells = screen.getAllByRole('textbox');
    const values = cells.map((c) => (c as HTMLInputElement).value);
    expect(values).toContain('Description');
    expect(values).toContain('CARD PAYMENT');
    expect(values).toContain('50.00');
  });
});
