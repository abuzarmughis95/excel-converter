/**
 * Theme context.
 *
 * Tracks the user's colour-scheme preference (light / dark / follow system) and
 * applies it by setting `data-theme` on the document root, which the stylesheet
 * keys off. The choice is persisted to localStorage (a UI preference, not a
 * secret) so it survives reloads. "system" leaves `data-theme` unset, letting
 * the prefers-color-scheme media query decide.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type JSX,
  type ReactNode,
} from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'ledgerline.theme';

export interface ThemeState {
  /** The user's stored preference. */
  preference: ThemePreference;
  /** The theme actually in effect right now ('light' | 'dark'). */
  resolved: 'light' | 'dark';
  setPreference: (next: ThemePreference) => void;
  /** Convenience: cycle the active light/dark theme. */
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function readStored(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') {
      return raw;
    }
  } catch {
    /* localStorage may be unavailable; fall through to default */
  }
  return 'system';
}

/**
 * Set `data-theme` from the stored preference before React mounts, avoiding a
 * flash of the wrong colour scheme. Safe to call once at startup. "system"
 * leaves the attribute unset so the prefers-color-scheme fallback applies.
 */
export function applyStoredThemeEarly(): void {
  const pref = readStored();
  const root = document.documentElement;
  if (pref === 'light' || pref === 'dark') {
    root.setAttribute('data-theme', pref);
  } else {
    root.removeAttribute('data-theme');
  }
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
}

export function ThemeProvider({ children }: { children: ReactNode }): JSX.Element {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => readStored());
  const [systemDark, setSystemDark] = useState<boolean>(() => systemPrefersDark());

  // Track OS changes so "system" stays live.
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e: MediaQueryListEvent): void => {
      setSystemDark(e.matches);
    };
    mq.addEventListener('change', onChange);
    return () => {
      mq.removeEventListener('change', onChange);
    };
  }, []);

  const resolved: 'light' | 'dark' =
    preference === 'system' ? (systemDark ? 'dark' : 'light') : preference;

  // Apply to the document root and persist.
  useEffect(() => {
    const root = document.documentElement;
    if (preference === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', preference);
    }
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      /* ignore persistence failures */
    }
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference): void => {
    setPreferenceState(next);
  }, []);

  const toggle = useCallback((): void => {
    setPreferenceState((prev) => {
      const current = prev === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : prev;
      return current === 'dark' ? 'light' : 'dark';
    });
  }, []);

  const value = useMemo<ThemeState>(
    () => ({ preference, resolved, setPreference, toggle }),
    [preference, resolved, setPreference, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
