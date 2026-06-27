import type { JSX } from 'react';
import { useEffect, useState } from 'react';

import type { AppInfo } from '../shared/ipc-contract.js';
import { AuthProvider, useAuth } from './auth/AuthContext.js';
import { LoginScreen } from './auth/LoginScreen.js';
import { CompanyProvider, useCompanies } from './company/CompanyContext.js';
import { CashbookScreen } from './screens/CashbookScreen.js';
import { ChartOfAccountsScreen } from './screens/ChartOfAccountsScreen.js';
import { CompaniesScreen } from './screens/CompaniesScreen.js';
import { DevicesScreen } from './screens/DevicesScreen.js';
import { FixedAssetsScreen } from './screens/FixedAssetsScreen.js';
import { JournalEntryScreen } from './screens/JournalEntryScreen.js';
import { PayrollScreen } from './screens/PayrollScreen.js';
import { PeriodsScreen } from './screens/PeriodsScreen.js';
import { ReconciliationScreen } from './screens/ReconciliationScreen.js';
import { ReportsScreen } from './screens/ReportsScreen.js';
import { VatReturnScreen } from './screens/VatReturnScreen.js';
import { SpreadsheetScreen } from './screens/SpreadsheetScreen.js';
import { StatementsScreen } from './screens/StatementsScreen.js';
import { ThemeProvider, useTheme } from './theme/ThemeContext.js';

/** Navigation targets. Several screens are wired to the backend; others are placeholders. */
const SCREENS = [
  'Dashboard',
  'Companies',
  'Bookkeeping',
  'Journals',
  'Bank Statements',
  'Cashbook',
  'Reconciliation',
  'Reports',
  'VAT',
  'Periods',
  'Fixed Assets',
  'Payroll',
  'Spreadsheet Bridge',
  'iXBRL Viewer',
  'Devices',
  'Sync Status',
  'Settings',
] as const;

type Screen = (typeof SCREENS)[number];

function useAppInfo(): AppInfo | null {
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (typeof window !== 'undefined' && 'ledgerline' in window) {
      window.ledgerline
        .getAppInfo()
        .then((info) => {
          if (!cancelled) {
            setAppInfo(info);
          }
        })
        .catch(() => {
          /* Non-fatal: banner simply omits version. */
        });
    }
    return () => {
      cancelled = true;
    };
  }, []);
  return appInfo;
}

function ScreenContent({ screen }: { screen: Screen }): JSX.Element {
  if (screen === 'Companies') {
    return <CompaniesScreen />;
  }
  if (screen === 'Bookkeeping') {
    return <ChartOfAccountsScreen />;
  }
  if (screen === 'Journals') {
    return <JournalEntryScreen />;
  }
  if (screen === 'Spreadsheet Bridge') {
    return <SpreadsheetScreen />;
  }
  if (screen === 'Bank Statements') {
    return <StatementsScreen />;
  }
  if (screen === 'Cashbook') {
    return <CashbookScreen />;
  }
  if (screen === 'Reconciliation') {
    return <ReconciliationScreen />;
  }
  if (screen === 'Reports') {
    return <ReportsScreen />;
  }
  if (screen === 'VAT') {
    return <VatReturnScreen />;
  }
  if (screen === 'Periods') {
    return <PeriodsScreen />;
  }
  if (screen === 'Fixed Assets') {
    return <FixedAssetsScreen />;
  }
  if (screen === 'Payroll') {
    return <PayrollScreen />;
  }
  if (screen === 'Devices') {
    return <DevicesScreen />;
  }
  return (
    <section aria-live="polite">
      <p>This module is not yet implemented.</p>
    </section>
  );
}

/** Light/dark theme toggle shown in the app header. */
function ThemeToggle(): JSX.Element {
  const { resolved, toggle } = useTheme();
  const goingDark = resolved === 'light';
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={goingDark ? 'Switch to dark mode' : 'Switch to light mode'}
      title={goingDark ? 'Switch to dark mode' : 'Switch to light mode'}
    >
      {goingDark ? '🌙 Dark' : '☀️ Light'}
    </button>
  );
}

/** The authenticated application shell. */
function AppShell(): JSX.Element {
  const { user, logout } = useAuth();
  const { activeCompany } = useCompanies();
  const [active, setActive] = useState<Screen>('Companies');
  const appInfo = useAppInfo();

  return (
    <div className="app-shell">
      <nav aria-label="Primary" className="app-nav">
        <h1 className="app-brand">Ledgerline</h1>
        {activeCompany !== null && <p className="app-active-company">{activeCompany.name}</p>}
        <ul>
          {SCREENS.map((screen) => (
            <li key={screen}>
              <button
                type="button"
                aria-current={screen === active ? 'page' : undefined}
                onClick={() => {
                  setActive(screen);
                }}
              >
                {screen}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <main className="app-main">
        <header className="app-header">
          <h2>{active}</h2>
          <div className="app-header-right">
            <ThemeToggle />
            {user !== null && <span className="app-user">{user.email}</span>}
            {appInfo !== null && (
              <span className="app-version">
                v{appInfo.appVersion} · {appInfo.platform}
              </span>
            )}
            <button type="button" className="app-logout" onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        </header>
        <ScreenContent screen={active} />
      </main>
    </div>
  );
}

/** Gates the app on authentication. */
function AuthGate(): JSX.Element {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? (
    <CompanyProvider>
      <AppShell />
    </CompanyProvider>
  ) : (
    <LoginScreen />
  );
}

export function App(): JSX.Element {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </ThemeProvider>
  );
}
