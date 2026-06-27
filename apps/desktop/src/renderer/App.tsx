import type { JSX } from 'react';
import { useEffect, useState } from 'react';

import type { AppInfo } from '../shared/ipc-contract.js';
import { AuthProvider, useAuth } from './auth/AuthContext.js';
import { LoginScreen } from './auth/LoginScreen.js';
import { CompanyProvider, useCompanies } from './company/CompanyContext.js';
import { ChartOfAccountsScreen } from './screens/ChartOfAccountsScreen.js';
import { CompaniesScreen } from './screens/CompaniesScreen.js';
import { DevicesScreen } from './screens/DevicesScreen.js';

/** Navigation targets. "Devices" is wired to the backend; others are placeholders. */
const SCREENS = [
  'Dashboard',
  'Companies',
  'Bookkeeping',
  'Cashbook',
  'VAT',
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
  if (screen === 'Devices') {
    return <DevicesScreen />;
  }
  return (
    <section aria-live="polite">
      <p>This module is not yet implemented.</p>
    </section>
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
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
