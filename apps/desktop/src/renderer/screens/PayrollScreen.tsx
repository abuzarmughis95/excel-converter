import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button, Form, Select, TextField } from '../components/ui/index.js';
import type {
  AccountResponse,
  EmployeeResponse,
  PayslipResponse,
} from '../lib/api-types.js';
import { errorMessage } from '../lib/errors.js';
import { money, parseMajorToMinor } from '../lib/money.js';

const NI_OPTIONS = [
  { value: 'A', label: 'A (standard)' },
  { value: 'X', label: 'X (no NI)' },
];
const FREQ_OPTIONS = [
  { value: 'monthly', label: 'Monthly' },
  { value: 'weekly', label: 'Weekly' },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Payroll: manage employees and run a pay period. A run computes each employee's
 * PAYE income tax and National Insurance via the engine, records payslips, and
 * posts one balanced wages journal. Tax/NI maths is the canonical engine's
 * (2025/26, non-cumulative basis).
 */
export function PayrollScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [employees, setEmployees] = useState<EmployeeResponse[]>([]);
  const [payslips, setPayslips] = useState<PayslipResponse[]>([]);
  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Employee form.
  const [name, setName] = useState('');
  const [salary, setSalary] = useState('');
  const [taxCode, setTaxCode] = useState('1257L');
  const [niCategory, setNiCategory] = useState('A');
  const [frequency, setFrequency] = useState('monthly');

  // Run form.
  const [periodLabel, setPeriodLabel] = useState('2026-06');
  const [payDate, setPayDate] = useState(todayIso());
  const [wagesAcc, setWagesAcc] = useState('');
  const [erNiAcc, setErNiAcc] = useState('');
  const [liabilityAcc, setLiabilityAcc] = useState('');
  const [netPayAcc, setNetPayAcc] = useState('');

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [emps, slips, accs] = await Promise.all([
        api.listEmployees(companyId),
        api.listPayslips(companyId),
        api.listAccounts(companyId),
      ]);
      setEmployees(emps);
      setPayslips(slips);
      setAccounts(accs.filter((a) => a.is_active));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load payroll.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function addEmployee(): Promise<void> {
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      await api.createEmployee(companyId, {
        name,
        annual_salary_minor: parseMajorToMinor(salary),
        tax_code: taxCode,
        ni_category: niCategory,
        pay_frequency: frequency,
      });
      setName('');
      setSalary('');
      setStatus('Employee added.');
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to add the employee.'));
    } finally {
      setBusy(false);
    }
  }

  async function runPayroll(): Promise<void> {
    if (companyId === null) {
      return;
    }
    if (wagesAcc === '' || erNiAcc === '' || liabilityAcc === '' || netPayAcc === '') {
      setError('Choose the wages, employer-NI, liability and net-pay accounts.');
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const result = await api.runPayroll(companyId, {
        period_label: periodLabel,
        pay_date: payDate,
        wages_account_id: wagesAcc,
        employer_ni_account_id: erNiAcc,
        liability_account_id: liabilityAcc,
        net_pay_account_id: netPayAcc,
      });
      setStatus(
        `Paid ${String(result.payslips.length)} employee(s) for ${result.period_label}: ` +
          `${money(result.total_net_minor)} net.`,
      );
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to run payroll.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  const accountOptions = [
    { value: '', label: '— select account —' },
    ...accounts.map((a) => ({ value: a.id, label: `${a.code} · ${a.name}` })),
  ];

  return (
    <section aria-live="polite" className="payroll-screen">
      <h3>Add employee</h3>
      <Form className="payroll-employee-form" onSubmit={() => void addEmployee()}>
        <TextField label="Name" value={name} onValueChange={setName} required />
        <TextField label="Annual salary (£)" value={salary} onValueChange={setSalary} required />
        <TextField label="Tax code" value={taxCode} onValueChange={setTaxCode} />
        <Select label="NI category" value={niCategory} onValueChange={setNiCategory} options={NI_OPTIONS} />
        <Select label="Frequency" value={frequency} onValueChange={setFrequency} options={FREQ_OPTIONS} />
        <Button type="submit" disabled={busy}>
          Add employee
        </Button>
      </Form>

      <table className="devices-table payroll-employees">
        <thead>
          <tr>
            <th>Employee</th>
            <th>Tax code</th>
            <th>NI</th>
            <th>Frequency</th>
            <th className="num">Annual salary</th>
          </tr>
        </thead>
        <tbody>
          {employees.length === 0 ? (
            <tr>
              <td colSpan={5}>No employees yet.</td>
            </tr>
          ) : (
            employees.map((e) => (
              <tr key={e.id}>
                <td>{e.name}</td>
                <td>{e.tax_code}</td>
                <td>{e.ni_category}</td>
                <td>{e.pay_frequency}</td>
                <td className="num">{money(e.annual_salary_minor)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <h3 className="payroll-run-heading">Run payroll</h3>
      <Form className="payroll-run-form" onSubmit={() => void runPayroll()}>
        <TextField label="Period label" value={periodLabel} onValueChange={setPeriodLabel} hint="e.g. 2026-06" />
        <TextField label="Pay date" type="date" value={payDate} onValueChange={setPayDate} />
        <Select label="Wages expense" value={wagesAcc} onValueChange={setWagesAcc} options={accountOptions} />
        <Select label="Employer NI expense" value={erNiAcc} onValueChange={setErNiAcc} options={accountOptions} />
        <Select label="PAYE/NI liability" value={liabilityAcc} onValueChange={setLiabilityAcc} options={accountOptions} />
        <Select label="Net pay payable" value={netPayAcc} onValueChange={setNetPayAcc} options={accountOptions} />
        <Button type="submit" disabled={busy || employees.length === 0}>
          Run payroll
        </Button>
      </Form>

      {accounts.length === 0 && <p>Add chart-of-accounts accounts (Bookkeeping) first.</p>}

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
      {status !== null && <p className="balanced">{status}</p>}

      <h3 className="payroll-run-heading">Payslips</h3>
      <table className="devices-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Employee</th>
            <th className="num">Gross</th>
            <th className="num">Tax</th>
            <th className="num">Employee NI</th>
            <th className="num">Net</th>
          </tr>
        </thead>
        <tbody>
          {payslips.length === 0 ? (
            <tr>
              <td colSpan={6}>No payslips yet. Run payroll above.</td>
            </tr>
          ) : (
            payslips.map((p) => (
              <tr key={p.id}>
                <td>{p.period_label}</td>
                <td>{p.employee_name}</td>
                <td className="num">{money(p.gross_minor)}</td>
                <td className="num">{money(p.income_tax_minor)}</td>
                <td className="num">{money(p.employee_ni_minor)}</td>
                <td className="num">{money(p.net_minor)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
