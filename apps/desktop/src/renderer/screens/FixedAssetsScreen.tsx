import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { useCompanies } from '../company/CompanyContext.js';
import { CompanyRequiredNotice } from '../components/CompanyRequiredNotice.js';
import { Button, Form, Select, TextField } from '../components/ui/index.js';
import type {
  AccountResponse,
  DepreciationMethod,
  FixedAssetResponse,
} from '../lib/api-types.js';
import { errorMessage } from '../lib/errors.js';
import { money, parseMajorToMinor } from '../lib/money.js';

const METHOD_OPTIONS = [
  { value: 'straight_line', label: 'Straight line' },
  { value: 'reducing_balance', label: 'Reducing balance' },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Fixed-asset register: register assets, see their net book value, and run one
 * period of depreciation (which posts Dr depreciation expense / Cr accumulated
 * depreciation via the engine). Depreciation maths is the canonical engine's.
 */
export function FixedAssetsScreen(): JSX.Element {
  const { api } = useAuth();
  const { activeCompany } = useCompanies();
  const companyId = activeCompany?.id ?? null;

  const [assets, setAssets] = useState<FixedAssetResponse[]>([]);
  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Create-form state.
  const [name, setName] = useState('');
  const [acquiredOn, setAcquiredOn] = useState(todayIso());
  const [cost, setCost] = useState('');
  const [residual, setResidual] = useState('0');
  const [method, setMethod] = useState<DepreciationMethod>('straight_line');
  const [life, setLife] = useState('36');
  const [rate, setRate] = useState('25');
  const [assetAcc, setAssetAcc] = useState('');
  const [accumAcc, setAccumAcc] = useState('');
  const [expenseAcc, setExpenseAcc] = useState('');

  const reload = useCallback(async (): Promise<void> => {
    if (companyId === null) {
      return;
    }
    setError(null);
    try {
      const [list, accs] = await Promise.all([
        api.listFixedAssets(companyId),
        api.listAccounts(companyId),
      ]);
      setAssets(list);
      setAccounts(accs.filter((a) => a.is_active));
    } catch (err) {
      setError(errorMessage(err, 'Failed to load the asset register.'));
    }
  }, [api, companyId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function create(): Promise<void> {
    if (companyId === null) {
      return;
    }
    if (assetAcc === '' || accumAcc === '' || expenseAcc === '') {
      setError('Choose the asset, accumulated-depreciation and expense accounts.');
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      await api.createFixedAsset(companyId, {
        name,
        acquired_on: acquiredOn,
        cost_minor: parseMajorToMinor(cost),
        residual_minor: parseMajorToMinor(residual),
        method,
        useful_life_periods: method === 'straight_line' ? Number(life) : null,
        rate_percent: method === 'reducing_balance' ? Number(rate) : null,
        asset_account_id: assetAcc,
        accumulated_account_id: accumAcc,
        expense_account_id: expenseAcc,
        category: null,
      });
      setName('');
      setCost('');
      setStatus('Asset registered.');
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to register the asset.'));
    } finally {
      setBusy(false);
    }
  }

  async function depreciate(asset: FixedAssetResponse): Promise<void> {
    if (companyId === null) {
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const result = await api.depreciateAsset(companyId, asset.id, todayIso());
      setStatus(
        result.charge_minor === 0
          ? `${asset.name} is already fully depreciated.`
          : `Charged ${money(result.charge_minor)} depreciation on ${asset.name}.`,
      );
      await reload();
    } catch (err) {
      setError(errorMessage(err, 'Failed to run depreciation.'));
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
    <section aria-live="polite" className="assets-screen">
      <Form className="assets-create" onSubmit={() => void create()}>
        <TextField label="Asset name" value={name} onValueChange={setName} required />
        <TextField label="Acquired" type="date" value={acquiredOn} onValueChange={setAcquiredOn} />
        <TextField label="Cost (£)" value={cost} onValueChange={setCost} required />
        <TextField label="Residual (£)" value={residual} onValueChange={setResidual} />
        <Select
          label="Method"
          value={method}
          onValueChange={(v) => {
            setMethod(v as DepreciationMethod);
          }}
          options={METHOD_OPTIONS}
        />
        {method === 'straight_line' ? (
          <TextField label="Life (periods)" type="number" value={life} onValueChange={setLife} />
        ) : (
          <TextField label="Rate (% / period)" value={rate} onValueChange={setRate} />
        )}
        <Select label="Asset account" value={assetAcc} onValueChange={setAssetAcc} options={accountOptions} />
        <Select
          label="Accumulated depreciation"
          value={accumAcc}
          onValueChange={setAccumAcc}
          options={accountOptions}
        />
        <Select
          label="Depreciation expense"
          value={expenseAcc}
          onValueChange={setExpenseAcc}
          options={accountOptions}
        />
        <Button type="submit" disabled={busy || accounts.length === 0}>
          Register asset
        </Button>
      </Form>

      {accounts.length === 0 && <p>Add chart-of-accounts accounts (Bookkeeping) first.</p>}

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}
      {status !== null && <p className="balanced">{status}</p>}

      <table className="devices-table assets-table">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Method</th>
            <th className="num">Cost</th>
            <th className="num">Accumulated</th>
            <th className="num">Net book value</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {assets.length === 0 ? (
            <tr>
              <td colSpan={6}>No assets registered yet.</td>
            </tr>
          ) : (
            assets.map((a) => (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td>
                  {a.method === 'straight_line'
                    ? `Straight line · ${String(a.useful_life_periods ?? 0)}p`
                    : `Reducing · ${String(a.rate_percent ?? 0)}%`}
                </td>
                <td className="num">{money(a.cost_minor)}</td>
                <td className="num">{money(a.accumulated_depreciation_minor)}</td>
                <td className="num">{money(a.net_book_value_minor)}</td>
                <td>
                  <Button disabled={busy} onClick={() => void depreciate(a)}>
                    Depreciate
                  </Button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
