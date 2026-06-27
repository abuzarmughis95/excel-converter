/**
 * Company context.
 *
 * Loads the signed-in user's companies and tracks the currently-selected
 * ("active") company, which other screens scope their data to. Kept separate
 * from auth so it can refresh independently when companies are created.
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

import { useAuth } from '../auth/AuthContext.js';
import type { CompanyResponse, CreateCompanyRequest } from '../lib/api-types.js';

export interface CompanyState {
  companies: CompanyResponse[];
  activeCompany: CompanyResponse | null;
  loading: boolean;
  selectCompany: (id: string) => void;
  createCompany: (body: CreateCompanyRequest) => Promise<CompanyResponse>;
  reload: () => Promise<void>;
}

const CompanyContext = createContext<CompanyState | null>(null);

export function CompanyProvider({ children }: { children: ReactNode }): JSX.Element {
  const { api, isAuthenticated } = useAuth();
  const [companies, setCompanies] = useState<CompanyResponse[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async (): Promise<void> => {
    if (!isAuthenticated) {
      setCompanies([]);
      setActiveId(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const list = await api.listCompanies();
      setCompanies(list);
      // Keep the current selection if still present; otherwise pick the first.
      setActiveId((current) => {
        if (current !== null && list.some((c) => c.id === current)) {
          return current;
        }
        const first = list[0];
        return first !== undefined ? first.id : null;
      });
    } catch {
      // A failed load leaves the company list empty rather than crashing the
      // app; the screen surfaces its own errors on explicit actions.
      setCompanies([]);
      setActiveId(null);
    } finally {
      setLoading(false);
    }
  }, [api, isAuthenticated]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const createCompany = useCallback(
    async (body: CreateCompanyRequest): Promise<CompanyResponse> => {
      const created = await api.createCompany(body);
      await reload();
      setActiveId(created.id);
      return created;
    },
    [api, reload],
  );

  const selectCompany = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const activeCompany = useMemo(
    () => companies.find((c) => c.id === activeId) ?? null,
    [companies, activeId],
  );

  const value = useMemo<CompanyState>(
    () => ({ companies, activeCompany, loading, selectCompany, createCompany, reload }),
    [companies, activeCompany, loading, selectCompany, createCompany, reload],
  );

  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>;
}

export function useCompanies(): CompanyState {
  const ctx = useContext(CompanyContext);
  if (ctx === null) {
    throw new Error('useCompanies must be used within a CompanyProvider');
  }
  return ctx;
}
