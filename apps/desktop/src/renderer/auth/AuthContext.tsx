/**
 * Authentication context.
 *
 * Holds the session in memory only — access and refresh tokens are kept in a
 * ref (never in localStorage/sessionStorage) to limit exposure to XSS, and the
 * user profile in React state for rendering. The shared ApiClient is wired to
 * read the current access token and to refresh transparently on a 401.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from 'react';

import { ApiClient } from '../lib/api-client.js';
import type { TokenResponse, UserResponse } from '../lib/api-types.js';

interface SessionTokens {
  accessToken: string;
  refreshToken: string;
}

export interface AuthState {
  user: UserResponse | null;
  isAuthenticated: boolean;
  api: ApiClient;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const tokensRef = useRef<SessionTokens | null>(null);
  const [user, setUser] = useState<UserResponse | null>(null);

  const refreshSession = useCallback(async (): Promise<string | null> => {
    const current = tokensRef.current;
    if (current === null) {
      return null;
    }
    try {
      const refreshed: TokenResponse = await api.refresh(current.refreshToken);
      tokensRef.current = {
        accessToken: refreshed.access_token,
        refreshToken: refreshed.refresh_token,
      };
      return refreshed.access_token;
    } catch {
      // Refresh failed: clear the session.
      tokensRef.current = null;
      setUser(null);
      return null;
    }
  }, []);

  // A single ApiClient instance for the lifetime of the provider.
  const api = useMemo(
    () =>
      new ApiClient({
        getAccessToken: () => tokensRef.current?.accessToken ?? null,
        refreshSession,
      }),
    [refreshSession],
  );

  const login = useCallback(
    async (email: string, password: string): Promise<void> => {
      const tokens = await api.login({ email, password });
      tokensRef.current = {
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      };
      const profile = await api.me();
      setUser(profile);
    },
    [api],
  );

  const logout = useCallback(async (): Promise<void> => {
    const current = tokensRef.current;
    tokensRef.current = null;
    setUser(null);
    if (current !== null) {
      try {
        await api.logout(current.refreshToken);
      } catch {
        // Best-effort server-side revocation; local state is already cleared.
      }
    }
  }, [api]);

  const value = useMemo<AuthState>(
    () => ({ user, isAuthenticated: user !== null, api, login, logout }),
    [user, api, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
