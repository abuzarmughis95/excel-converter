/**
 * Typed HTTP client for the backend API.
 *
 * Responsibilities:
 *  - serialise/deserialise JSON and surface a typed {@link ApiError} on failure;
 *  - attach the current access token (provided by a callback so the client does
 *    not own auth state);
 *  - transparently refresh the access token once on a 401 and retry, using a
 *    caller-supplied refresh function.
 *
 * Tokens are never persisted by this client; the auth store keeps them in
 * memory (see auth-store) to limit exposure to XSS.
 */

import { API_BASE_URL } from './config.js';
import type {
  CompanyResponse,
  CreateCompanyRequest,
  AccountResponse,
  BankAccountResponse,
  BankStatementLineResponse,
  CreateAccountRequest,
  CreateBankAccountRequest,
  CreateJournalRequest,
  DeviceResponse,
  ExtractStatementResponse,
  BalanceSheetResponse,
  ImportLineModel,
  ImportResultResponse,
  JournalResponse,
  LoginRequest,
  PeriodResponse,
  PeriodStatus,
  ProfitAndLossResponse,
  VatReturnResponse,
  VatSubmissionResponse,
  ReconcilableLineResponse,
  MatchSuggestionResponse,
  ReconciliationSummaryResponse,
  RegisterDeviceRequest,
  RegisterDeviceResponse,
  SaveWorkbookRequest,
  TokenResponse,
  TrialBalanceRow,
  UserResponse,
  WorkbookResponse,
} from './api-types.js';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export interface ApiClientOptions {
  /** Returns the current access token, or null when unauthenticated. */
  getAccessToken: () => string | null;
  /**
   * Attempts to refresh the session after a 401. Returns the new access token
   * on success, or null if refresh failed (caller should then log out).
   */
  refreshSession?: () => Promise<string | null>;
  /** Override the base URL (mainly for tests). */
  baseUrl?: string;
  /** Injectable fetch (mainly for tests). */
  fetchFn?: typeof fetch;
}

interface RequestOptions {
  method: string;
  path: string;
  body?: unknown;
  auth?: boolean;
  /** Internal: prevents infinite refresh recursion. */
  _isRetry?: boolean;
}

function extractMessage(status: number, payload: unknown): string {
  if (payload !== null && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
  }
  return `Request failed with status ${String(status)}`;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchFn: typeof fetch;
  private readonly getAccessToken: () => string | null;
  private readonly refreshSession: (() => Promise<string | null>) | undefined;

  constructor(options: ApiClientOptions) {
    this.baseUrl = (options.baseUrl ?? API_BASE_URL).replace(/\/+$/, '');
    this.fetchFn = options.fetchFn ?? fetch.bind(globalThis);
    this.getAccessToken = options.getAccessToken;
    this.refreshSession = options.refreshSession;
  }

  private async request<T>(opts: RequestOptions): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (opts.auth === true) {
      const token = this.getAccessToken();
      if (token !== null) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    }

    const init: RequestInit = { method: opts.method, headers };
    if (opts.body !== undefined) {
      init.body = JSON.stringify(opts.body);
    }
    const response = await this.fetchFn(`${this.baseUrl}${opts.path}`, init);

    // Transparently refresh once on a 401 for authenticated requests.
    if (
      response.status === 401 &&
      opts.auth === true &&
      opts._isRetry !== true &&
      this.refreshSession !== undefined
    ) {
      const newToken = await this.refreshSession();
      if (newToken !== null) {
        return this.request<T>({ ...opts, _isRetry: true });
      }
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const text = await response.text();
    const payload: unknown = text.length > 0 ? JSON.parse(text) : null;

    if (!response.ok) {
      throw new ApiError(response.status, extractMessage(response.status, payload), payload);
    }
    return payload as T;
  }

  // -- auth -------------------------------------------------------------

  login(body: LoginRequest): Promise<TokenResponse> {
    return this.request<TokenResponse>({ method: 'POST', path: '/auth/login', body });
  }

  refresh(refreshToken: string): Promise<TokenResponse> {
    return this.request<TokenResponse>({
      method: 'POST',
      path: '/auth/refresh',
      body: { refresh_token: refreshToken },
    });
  }

  async logout(refreshToken: string): Promise<void> {
    await this.request<undefined>({
      method: 'POST',
      path: '/auth/logout',
      body: { refresh_token: refreshToken },
    });
  }

  me(): Promise<UserResponse> {
    return this.request<UserResponse>({ method: 'GET', path: '/auth/me', auth: true });
  }

  // -- devices ----------------------------------------------------------

  registerDevice(body: RegisterDeviceRequest): Promise<RegisterDeviceResponse> {
    return this.request<RegisterDeviceResponse>({
      method: 'POST',
      path: '/auth/devices/register',
      body,
      auth: true,
    });
  }

  listDevices(): Promise<DeviceResponse[]> {
    return this.request<DeviceResponse[]>({ method: 'GET', path: '/auth/devices', auth: true });
  }

  async revokeDevice(deviceId: string): Promise<void> {
    await this.request<undefined>({
      method: 'POST',
      path: `/auth/devices/${deviceId}/revoke`,
      auth: true,
    });
  }

  // -- companies --------------------------------------------------------

  listCompanies(): Promise<CompanyResponse[]> {
    return this.request<CompanyResponse[]>({ method: 'GET', path: '/companies', auth: true });
  }

  createCompany(body: CreateCompanyRequest): Promise<CompanyResponse> {
    return this.request<CompanyResponse>({
      method: 'POST',
      path: '/companies',
      body,
      auth: true,
    });
  }

  // -- chart of accounts ------------------------------------------------

  listAccounts(companyId: string): Promise<AccountResponse[]> {
    return this.request<AccountResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/accounts`,
      auth: true,
    });
  }

  createAccount(companyId: string, body: CreateAccountRequest): Promise<AccountResponse> {
    return this.request<AccountResponse>({
      method: 'POST',
      path: `/companies/${companyId}/accounts`,
      body,
      auth: true,
    });
  }

  deactivateAccount(companyId: string, accountId: string): Promise<AccountResponse> {
    return this.request<AccountResponse>({
      method: 'POST',
      path: `/companies/${companyId}/accounts/${accountId}/deactivate`,
      auth: true,
    });
  }

  // -- journals + trial balance -----------------------------------------

  listJournals(companyId: string): Promise<JournalResponse[]> {
    return this.request<JournalResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/journals`,
      auth: true,
    });
  }

  createJournal(companyId: string, body: CreateJournalRequest): Promise<JournalResponse> {
    return this.request<JournalResponse>({
      method: 'POST',
      path: `/companies/${companyId}/journals`,
      body,
      auth: true,
    });
  }

  postJournal(companyId: string, journalId: string): Promise<JournalResponse> {
    return this.request<JournalResponse>({
      method: 'POST',
      path: `/companies/${companyId}/journals/${journalId}/post`,
      auth: true,
    });
  }

  unpostJournal(
    companyId: string,
    journalId: string,
    reason: string,
  ): Promise<JournalResponse> {
    return this.request<JournalResponse>({
      method: 'POST',
      path: `/companies/${companyId}/journals/${journalId}/unpost`,
      body: { reason },
      auth: true,
    });
  }

  reverseJournal(
    companyId: string,
    journalId: string,
    reason: string,
    reversalDate: string | null,
  ): Promise<JournalResponse> {
    return this.request<JournalResponse>({
      method: 'POST',
      path: `/companies/${companyId}/journals/${journalId}/reverse`,
      body: { reason, reversal_date: reversalDate },
      auth: true,
    });
  }

  trialBalance(companyId: string): Promise<TrialBalanceRow[]> {
    return this.request<TrialBalanceRow[]>({
      method: 'GET',
      path: `/companies/${companyId}/trial-balance`,
      auth: true,
    });
  }

  profitAndLoss(companyId: string): Promise<ProfitAndLossResponse> {
    return this.request<ProfitAndLossResponse>({
      method: 'GET',
      path: `/companies/${companyId}/profit-and-loss`,
      auth: true,
    });
  }

  balanceSheet(companyId: string): Promise<BalanceSheetResponse> {
    return this.request<BalanceSheetResponse>({
      method: 'GET',
      path: `/companies/${companyId}/balance-sheet`,
      auth: true,
    });
  }

  vatReturn(companyId: string): Promise<VatReturnResponse> {
    return this.request<VatReturnResponse>({
      method: 'GET',
      path: `/companies/${companyId}/vat-return`,
      auth: true,
    });
  }

  listVatSubmissions(companyId: string): Promise<VatSubmissionResponse[]> {
    return this.request<VatSubmissionResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/vat-submissions`,
      auth: true,
    });
  }

  finaliseVatReturn(
    companyId: string,
    periodStart: string,
    periodEnd: string,
    reference: string,
    lockPeriod: boolean,
  ): Promise<VatSubmissionResponse> {
    return this.request<VatSubmissionResponse>({
      method: 'POST',
      path: `/companies/${companyId}/vat-submissions`,
      body: {
        period_start: periodStart,
        period_end: periodEnd,
        reference,
        lock_period: lockPeriod,
      },
      auth: true,
    });
  }

  // -- accounting periods ----------------------------------------------

  listPeriods(companyId: string): Promise<PeriodResponse[]> {
    return this.request<PeriodResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/periods`,
      auth: true,
    });
  }

  createPeriod(
    companyId: string,
    fiscalYear: number,
    startsOn: string,
    endsOn: string,
  ): Promise<PeriodResponse> {
    return this.request<PeriodResponse>({
      method: 'POST',
      path: `/companies/${companyId}/periods`,
      body: { fiscal_year: fiscalYear, starts_on: startsOn, ends_on: endsOn },
      auth: true,
    });
  }

  setPeriodStatus(
    companyId: string,
    periodId: string,
    statusValue: PeriodStatus,
  ): Promise<PeriodResponse> {
    return this.request<PeriodResponse>({
      method: 'POST',
      path: `/companies/${companyId}/periods/${periodId}/status`,
      body: { status: statusValue },
      auth: true,
    });
  }

  // -- workbook (spreadsheet) -------------------------------------------

  loadWorkbook(companyId: string): Promise<WorkbookResponse> {
    return this.request<WorkbookResponse>({
      method: 'GET',
      path: `/companies/${companyId}/workbook`,
      auth: true,
    });
  }

  saveWorkbook(companyId: string, body: SaveWorkbookRequest): Promise<WorkbookResponse> {
    return this.request<WorkbookResponse>({
      method: 'PUT',
      path: `/companies/${companyId}/workbook`,
      body,
      auth: true,
    });
  }

  // -- bank statement extraction (multipart upload) ---------------------

  async extractStatement(companyId: string, file: File): Promise<ExtractStatementResponse> {
    const form = new FormData();
    form.append('file', file);
    const token = this.getAccessToken();
    const headers: Record<string, string> = {};
    if (token !== null) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    // FormData sets its own Content-Type (with boundary); do not override it.
    const response = await this.fetchFn(
      `${this.baseUrl}/companies/${companyId}/statements/extract`,
      { method: 'POST', headers, body: form },
    );
    const text = await response.text();
    const payload: unknown = text.length > 0 ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail =
        payload !== null && typeof payload === 'object' && 'detail' in payload
          ? String((payload as { detail: unknown }).detail)
          : `Upload failed (${String(response.status)})`;
      throw new ApiError(response.status, detail, payload);
    }
    return payload as ExtractStatementResponse;
  }

  // -- cashbook (bank accounts, import, post) ---------------------------

  listBankAccounts(companyId: string): Promise<BankAccountResponse[]> {
    return this.request<BankAccountResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/bank-accounts`,
      auth: true,
    });
  }

  createBankAccount(
    companyId: string,
    body: CreateBankAccountRequest,
  ): Promise<BankAccountResponse> {
    return this.request<BankAccountResponse>({
      method: 'POST',
      path: `/companies/${companyId}/bank-accounts`,
      body,
      auth: true,
    });
  }

  importStatementLines(
    companyId: string,
    bankAccountId: string,
    lines: ImportLineModel[],
  ): Promise<ImportResultResponse> {
    return this.request<ImportResultResponse>({
      method: 'POST',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/import`,
      body: { lines },
      auth: true,
    });
  }

  listStatementLines(
    companyId: string,
    bankAccountId: string,
  ): Promise<BankStatementLineResponse[]> {
    return this.request<BankStatementLineResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/lines`,
      auth: true,
    });
  }

  postStatementLine(
    companyId: string,
    bankAccountId: string,
    lineId: string,
    contraAccountId: string,
  ): Promise<{ journal_id: string }> {
    return this.request<{ journal_id: string }>({
      method: 'POST',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/lines/${lineId}/post`,
      body: { contra_account_id: contraAccountId },
      auth: true,
    });
  }

  // -- reconciliation ---------------------------------------------------

  listReconcilableLines(
    companyId: string,
    bankAccountId: string,
  ): Promise<ReconcilableLineResponse[]> {
    return this.request<ReconcilableLineResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/reconciliation`,
      auth: true,
    });
  }

  async setLineReconciled(
    companyId: string,
    bankAccountId: string,
    journalLineId: string,
    reconciled: boolean,
  ): Promise<void> {
    await this.request<undefined>({
      method: 'POST',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/reconciliation/${journalLineId}`,
      body: { reconciled },
      auth: true,
    });
  }

  reconciliationSummary(
    companyId: string,
    bankAccountId: string,
    statementBalanceMinor: number | null,
  ): Promise<ReconciliationSummaryResponse> {
    const query =
      statementBalanceMinor !== null
        ? `?statement_balance_minor=${String(statementBalanceMinor)}`
        : '';
    return this.request<ReconciliationSummaryResponse>({
      method: 'GET',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/reconciliation-summary${query}`,
      auth: true,
    });
  }

  reconciliationSuggestions(
    companyId: string,
    bankAccountId: string,
  ): Promise<MatchSuggestionResponse[]> {
    return this.request<MatchSuggestionResponse[]>({
      method: 'GET',
      path: `/companies/${companyId}/bank-accounts/${bankAccountId}/reconciliation-suggestions`,
      auth: true,
    });
  }
}
