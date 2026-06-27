import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button, Form, TextField } from '../components/ui/index.js';
import type { PeriodResponse, PeriodStatus } from '../lib/api-types.js';
import { errorMessage } from '../lib/errors.js';

const STATUS_LABEL: Record<PeriodStatus, string> = {
  open: 'Open',
  soft_closed: 'Soft-closed',
  locked: 'Locked',
};

/** Legal next states from the engine state machine, mirrored for the UI. */
function nextStates(status: PeriodStatus): PeriodStatus[] {
  if (status === 'open') {
    return ['soft_closed', 'locked'];
  }
  if (status === 'soft_closed') {
    return ['open', 'locked'];
  }
  return [];
}

/**
 * Accounting Periods: create fiscal periods and move them open ->
 * soft-closed -> locked. Posting into a soft-closed or locked period is blocked
 * by the backend. Managing periods requires accountant+.
 */
export function PeriodsScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [periods, setPeriods] = useState<PeriodResponse[]>([]);
  const [year, setYear] = useState('2026');
  const [startsOn, setStartsOn] = useState('2026-01-01');
  const [endsOn, setEndsOn] = useState('2026-12-31');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      setPeriods(await api.listPeriods(companyId));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load periods.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function create(): Promise<void> {
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createPeriod(companyId, Number(year), startsOn, endsOn);
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create the period.'));
    } finally {
      setBusy(false);
    }
  }

  async function transition(period: PeriodResponse, target: PeriodStatus): Promise<void> {
    if (companyId === null) {
      return;
    }
    if (target === 'locked' && !window.confirm('Lock this period? Locked periods are final.')) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.setPeriodStatus(companyId, period.id, target);
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to change the status.'));
    } finally {
      setBusy(false);
    }
  }

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  return (
    <section aria-live="polite" className="periods-screen">
      <Form
        className="periods-create"
        onSubmit={() => {
          void create();
        }}
      >
        <TextField
          label="Fiscal year"
          type="number"
          value={year}
          onValueChange={setYear}
          min={1900}
          max={3000}
        />
        <TextField label="Starts" type="date" value={startsOn} onValueChange={setStartsOn} />
        <TextField label="Ends" type="date" value={endsOn} onValueChange={setEndsOn} />
        <Button type="submit" disabled={busy}>
          Add period
        </Button>
      </Form>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      <table className="devices-table">
        <thead>
          <tr>
            <th>Year</th>
            <th>From</th>
            <th>To</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {periods.length === 0 ? (
            <tr>
              <td colSpan={5}>No periods yet. Add one above.</td>
            </tr>
          ) : (
            periods.map((p) => (
              <tr key={p.id}>
                <td>{p.fiscal_year}</td>
                <td>{p.starts_on}</td>
                <td>{p.ends_on}</td>
                <td>
                  <span className={`period-status period-${p.status}`}>
                    {STATUS_LABEL[p.status]}
                  </span>
                </td>
                <td>
                  {nextStates(p.status).map((target) => (
                    <button
                      key={target}
                      type="button"
                      disabled={busy}
                      className="period-action"
                      onClick={() => void transition(p, target)}
                    >
                      {target === 'open'
                        ? 'Reopen'
                        : target === 'soft_closed'
                          ? 'Soft-close'
                          : 'Lock'}
                    </button>
                  ))}
                  {nextStates(p.status).length === 0 && <span style={{ opacity: 0.6 }}>—</span>}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
