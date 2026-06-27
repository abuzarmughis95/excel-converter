import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { ApiError } from '../lib/api-client.js';
import type { VatReturnResponse } from '../lib/api-types.js';

function money(minor: number): string {
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  return `£${sign}${Math.trunc(abs / 100).toString()}.${(abs % 100).toString().padStart(2, '0')}`;
}

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
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      setVat(await api.vatReturn(companyId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the VAT return.');
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (activeCompany === null) {
    return (
      <section aria-live="polite">
        <p>Select or create a company first (Companies screen).</p>
      </section>
    );
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
    </section>
  );
}
