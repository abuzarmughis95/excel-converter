import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button, Checkbox } from '../components/ui/index.js';
import { errorMessage } from '../lib/errors.js';
import type { VatReturnResponse, VatSubmissionResponse } from '../lib/api-types.js';
import { money } from '../lib/money.js';

interface BoxDef {
  n: number;
  label: string;
  key: keyof VatReturnResponse;
}

const BOXES: BoxDef[] = [
  { n: 1, label: 'VAT due on sales and other outputs', key: 'box1_minor' },
  { n: 2, label: 'VAT due on acquisitions from EC member states', key: 'box2_minor' },
  { n: 3, label: 'Total VAT due (Box 1 + Box 2)', key: 'box3_minor' },
  { n: 4, label: 'VAT reclaimed on purchases and other inputs', key: 'box4_minor' },
  { n: 5, label: 'Net VAT to pay HMRC or reclaim', key: 'box5_minor' },
  { n: 6, label: 'Total value of sales excluding VAT', key: 'box6_minor' },
  { n: 7, label: 'Total value of purchases excluding VAT', key: 'box7_minor' },
  { n: 8, label: 'Total value of EC supplies of goods excluding VAT', key: 'box8_minor' },
  { n: 9, label: 'Total value of EC acquisitions of goods excluding VAT', key: 'box9_minor' },
];

/**
 * VAT Return: the 9-box UK VAT return computed by the engine over posted
 * journals. Box values are derived from journal lines that carry a VAT code.
 */
export function VatReturnScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [vat, setVat] = useState<VatReturnResponse | null>(null);
  const [submissions, setSubmissions] = useState<VatSubmissionResponse[]>([]);
  const [periodStart, setPeriodStart] = useState('2026-01-01');
  const [periodEnd, setPeriodEnd] = useState('2026-03-31');
  const [reference, setReference] = useState('');
  const [lockPeriod, setLockPeriod] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [vr, subs] = await Promise.all([
        api.vatReturn(companyId),
        api.listVatSubmissions(companyId),
      ]);
      setVat(vr);
      setSubmissions(subs);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load the VAT return.'));
    }
  }, [api, companyId]);

  async function finalise(): Promise<void> {
    if (companyId === null) {
      return;
    }
    if (reference.trim() === '') {
      setError('Enter a submission reference (e.g. the HMRC receipt number).');
      return;
    }
    if (!window.confirm('Finalise this VAT return? The figures will be snapshotted.')) {
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const sub = await api.finaliseVatReturn(
        companyId,
        periodStart,
        periodEnd,
        reference.trim(),
        lockPeriod,
      );
      setStatus(`Finalised ${sub.period_start} to ${sub.period_end} (ref ${sub.reference}).`);
      setReference('');
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to finalise the return.'));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [reload]);

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  const net = vat?.box5_minor ?? 0;
  const payable = (vat?.box3_minor ?? 0) >= (vat?.box4_minor ?? 0);

  return (
    <section aria-live="polite" className="vat-screen">
      <h2 className="vat-title">VAT Return</h2>
      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
      {vat !== null && (
        <>
          <table className="report-table vat-table">
            <tbody>
              {BOXES.map((box) => (
                <tr key={box.n} className={box.n === 5 ? 'report-grand' : ''}>
                  <td className="vat-box-no">Box {box.n}</td>
                  <td>{box.label}</td>
                  <td className="num">{money(vat[box.key])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="vat-conclusion">
            {net === 0
              ? 'Nothing to pay or reclaim this period.'
              : payable
                ? `${money(net)} payable to HMRC.`
                : `${money(net)} reclaimable from HMRC.`}
          </p>
        </>
      )}

      <form
        className="vat-finalise"
        onSubmit={(e) => {
          e.preventDefault();
          void finalise();
        }}
      >
        <h3>Finalise return</h3>
        <div className="vat-finalise-row">
          <label>
            Period start{' '}
            <input
              type="date"
              value={periodStart}
              onChange={(e) => {
                setPeriodStart(e.target.value);
              }}
            />
          </label>
          <label>
            Period end{' '}
            <input
              type="date"
              value={periodEnd}
              onChange={(e) => {
                setPeriodEnd(e.target.value);
              }}
            />
          </label>
          <label>
            Reference{' '}
            <input
              type="text"
              placeholder="HMRC receipt"
              value={reference}
              onChange={(e) => {
                setReference(e.target.value);
              }}
            />
          </label>
          <Checkbox label="Lock period" checked={lockPeriod} onCheckedChange={setLockPeriod} />
          <Button type="submit" disabled={busy}>
            Finalise
          </Button>
        </div>
        {status !== null && <p className="balanced">{status}</p>}
      </form>

      {submissions.length > 0 && (
        <div className="vat-history">
          <h3>Submitted returns</h3>
          <table className="devices-table">
            <thead>
              <tr>
                <th>Period</th>
                <th>Reference</th>
                <th className="num">Box 5 (net)</th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.period_start} to {s.period_end}
                  </td>
                  <td>{s.reference}</td>
                  <td className="num">{money(s.boxes.box5_minor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
