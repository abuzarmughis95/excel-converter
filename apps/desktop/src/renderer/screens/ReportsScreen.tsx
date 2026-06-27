import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { errorMessage } from '../lib/errors.js';
import type { BalanceSheetResponse, ProfitAndLossResponse, ReportLine } from '../lib/api-types.js';
import { money } from '../lib/money.js';

type Tab = 'pnl' | 'bs';

function LineRows({ lines }: { lines: ReportLine[] }): JSX.Element {
  return (
    <>
      {lines.map((l) => (
        <tr key={l.account_code}>
          <td>
            {l.account_code} · {l.account_name}
          </td>
          <td className="num">{money(l.amount_minor)}</td>
        </tr>
      ))}
    </>
  );
}

/**
 * Reports screen: Profit & Loss and Balance Sheet for the active company,
 * computed by the accounting engine over posted journals. The balance sheet
 * folds the period's net profit into retained earnings so it balances.
 */
export function ReportsScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [tab, setTab] = useState<Tab>('pnl');
  const [pnl, setPnl] = useState<ProfitAndLossResponse | null>(null);
  const [bs, setBs] = useState<BalanceSheetResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [p, b] = await Promise.all([
        api.profitAndLoss(companyId),
        api.balanceSheet(companyId),
      ]);
      setPnl(p);
      setBs(b);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load reports.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (activeCompany === null) {
    return <CompanyRequiredNotice />;
  }

  return (
    <section aria-live="polite" className="reports-screen">
      <div className="reports-tabs">
        <button
          type="button"
          className={tab === 'pnl' ? 'active' : ''}
          onClick={() => {
            setTab('pnl');
          }}
        >
          Profit &amp; Loss
        </button>
        <button
          type="button"
          className={tab === 'bs' ? 'active' : ''}
          onClick={() => {
            setTab('bs');
          }}
        >
          Balance Sheet
        </button>
      </div>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {tab === 'pnl' && pnl !== null && (
        <table className="report-table">
          <tbody>
            <tr className="report-heading">
              <td colSpan={2}>Income</td>
            </tr>
            <LineRows lines={pnl.income} />
            <tr className="report-total">
              <td>Total income</td>
              <td className="num">{money(pnl.total_income_minor)}</td>
            </tr>
            <tr className="report-heading">
              <td colSpan={2}>Expenses</td>
            </tr>
            <LineRows lines={pnl.expenses} />
            <tr className="report-total">
              <td>Total expenses</td>
              <td className="num">{money(pnl.total_expenses_minor)}</td>
            </tr>
            <tr className="report-grand">
              <td>{pnl.net_profit_minor >= 0 ? 'Net profit' : 'Net loss'}</td>
              <td className="num">{money(pnl.net_profit_minor)}</td>
            </tr>
          </tbody>
        </table>
      )}

      {tab === 'bs' && bs !== null && (
        <table className="report-table">
          <tbody>
            <tr className="report-heading">
              <td colSpan={2}>Assets</td>
            </tr>
            <LineRows lines={bs.assets} />
            <tr className="report-total">
              <td>Total assets</td>
              <td className="num">{money(bs.total_assets_minor)}</td>
            </tr>
            <tr className="report-heading">
              <td colSpan={2}>Liabilities</td>
            </tr>
            <LineRows lines={bs.liabilities} />
            <tr className="report-total">
              <td>Total liabilities</td>
              <td className="num">{money(bs.total_liabilities_minor)}</td>
            </tr>
            <tr className="report-heading">
              <td colSpan={2}>Equity</td>
            </tr>
            <LineRows lines={bs.equity} />
            <tr>
              <td>Retained earnings</td>
              <td className="num">{money(bs.retained_earnings_minor)}</td>
            </tr>
            <tr className="report-total">
              <td>Total equity</td>
              <td className="num">{money(bs.total_equity_minor)}</td>
            </tr>
            <tr className="report-grand">
              <td>Liabilities + Equity</td>
              <td className="num">
                {money(bs.total_liabilities_minor + bs.total_equity_minor)}
              </td>
            </tr>
          </tbody>
        </table>
      )}
    </section>
  );
}
