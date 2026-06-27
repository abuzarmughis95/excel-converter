import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../auth/AuthContext.js';
import { CompanyProvider } from '../company/CompanyContext.js';
import { PayrollScreen } from './PayrollScreen.js';

let ran = false;

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

const EMPLOYEE = {
  id: 'e-1',
  name: 'Alice',
  annual_salary_minor: 3600000,
  tax_code: '1257L',
  ni_category: 'A',
  pay_frequency: 'monthly',
  active: true,
};

const PAYSLIP = {
  id: 'p-1',
  employee_id: 'e-1',
  employee_name: 'Alice',
  period_label: '2026-06',
  pay_date: '2026-06-28',
  gross_minor: 300000,
  income_tax_minor: 39050,
  employee_ni_minor: 15620,
  employer_ni_minor: 38750,
  net_minor: 245330,
  journal_id: 'j-1',
};

const ACCOUNTS = [
  { id: 'a-1', code: '7000', name: 'Wages', account_type: 'expense', normal_balance: 'DR', is_active: true },
  { id: 'a-2', code: '7010', name: 'Employer NI', account_type: 'expense', normal_balance: 'DR', is_active: true },
  { id: 'a-3', code: '2210', name: 'PAYE liability', account_type: 'liability', normal_balance: 'CR', is_active: true },
  { id: 'a-4', code: '2220', name: 'Net pay', account_type: 'liability', normal_balance: 'CR', is_active: true },
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
    if (url.endsWith('/payroll/employees') && method === 'GET') {
      return json(200, [EMPLOYEE]);
    }
    if (url.endsWith('/payroll/payslips') && method === 'GET') {
      return json(200, ran ? [PAYSLIP] : []);
    }
    if (url.endsWith('/payroll/runs') && method === 'POST') {
      ran = true;
      return json(201, { period_label: '2026-06', journal_id: 'j-1', payslips: [PAYSLIP], total_gross_minor: 300000, total_net_minor: 245330 });
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
      <PayrollScreen />
    </CompanyProvider>
  );
}

beforeEach(() => {
  ran = false;
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PayrollScreen', () => {
  it('lists employees and runs payroll, showing the payslip breakdown', async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <PreAuth />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument();
    });

    // Choose the four GL accounts then run.
    await user.selectOptions(screen.getByLabelText('Wages expense'), 'a-1');
    await user.selectOptions(screen.getByLabelText('Employer NI expense'), 'a-2');
    await user.selectOptions(screen.getByLabelText('PAYE/NI liability'), 'a-3');
    await user.selectOptions(screen.getByLabelText('Net pay payable'), 'a-4');
    await user.click(screen.getByRole('button', { name: 'Run payroll' }));

    // The run status reports the net pay.
    await waitFor(() => {
      expect(screen.getByText(/Paid 1 employee\(s\)/)).toBeInTheDocument();
    });
    // After the payslips reload, the breakdown row shows the tax (£390.50),
    // employee NI (£156.20) and net pay (£2453.30).
    await waitFor(() => {
      expect(screen.getByText('£390.50')).toBeInTheDocument();
    });
    expect(screen.getByText('£156.20')).toBeInTheDocument();
    expect(screen.getAllByText('£2453.30').length).toBeGreaterThanOrEqual(1);
  });
});
