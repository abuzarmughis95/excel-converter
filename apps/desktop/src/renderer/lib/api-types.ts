/**
 * Request/response types mirroring the backend auth + device API.
 *
 * These are hand-authored for now; once the backend's OpenAPI spec is published
 * (ticket F-11), this module is replaced by generated types so the contract
 * cannot drift.
 */

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  mfa_required: boolean;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
  status: string;
}

export interface RegisterDeviceRequest {
  name: string;
  platform: string;
  public_key_b64: string;
}

export interface RegisterDeviceResponse {
  device_id: string;
  node_id: number;
  entitlement_exp: string;
}

export interface DeviceResponse {
  id: string;
  node_id: number;
  name: string;
  platform: string;
  entitlement_exp: string;
  revoked: boolean;
}

export interface CompanyResponse {
  id: string;
  name: string;
  base_currency: string;
  accounts_type: string;
  companies_house_no: string | null;
  vat_registration_no: string | null;
  role: string;
}

export interface CreateCompanyRequest {
  name: string;
  base_currency?: string;
  accounts_type?: string;
}

export interface AccountResponse {
  id: string;
  code: string;
  name: string;
  account_type: string;
  normal_balance: string;
  is_control: boolean;
  control_kind: string | null;
  is_active: boolean;
}

export interface CreateAccountRequest {
  code: string;
  name: string;
  account_type: string;
  control_kind?: string | null;
}

export interface JournalLineInput {
  account_id: string;
  debit_minor?: number;
  credit_minor?: number;
  narrative?: string | null;
}

export interface CreateJournalRequest {
  journal_date: string;
  lines: JournalLineInput[];
  currency?: string;
  reference?: string | null;
  narrative?: string | null;
}

export interface JournalLineResponse {
  line_no: number;
  account_id: string;
  account_code: string;
  account_name: string;
  debit_minor: number;
  credit_minor: number;
  narrative: string | null;
}

export interface JournalResponse {
  id: string;
  journal_date: string;
  journal_type: string;
  reference: string | null;
  narrative: string | null;
  currency: string;
  is_posted: boolean;
  lines: JournalLineResponse[];
}

export interface TrialBalanceRow {
  account_code: string;
  account_name: string;
  debit_minor: number;
  credit_minor: number;
}

export interface ReportLine {
  account_code: string;
  account_name: string;
  amount_minor: number;
}

export interface ProfitAndLossResponse {
  income: ReportLine[];
  expenses: ReportLine[];
  total_income_minor: number;
  total_expenses_minor: number;
  net_profit_minor: number;
}

export interface BalanceSheetResponse {
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets_minor: number;
  total_liabilities_minor: number;
  total_equity_minor: number;
  retained_earnings_minor: number;
}

export interface SheetData {
  name: string;
  sort_order: number;
  cells: string[][];
}

export interface WorkbookResponse {
  id: string;
  name: string;
  sheets: SheetData[];
}

export interface SaveWorkbookRequest {
  sheets: { name: string; cells: string[][] }[];
}

export interface StatementLine {
  date: string | null;
  description: string;
  money_out_minor: number;
  money_in_minor: number;
  balance_minor: number | null;
}

export interface StatementSummary {
  account_name: string | null;
  account_number: string | null;
  sort_code: string | null;
  period_start: string | null;
  period_end: string | null;
  opening_balance_minor: number | null;
  closing_balance_minor: number | null;
}

export interface ExtractStatementResponse {
  currency: string;
  reconciled: boolean;
  summary: StatementSummary;
  lines: StatementLine[];
}

export interface BankAccountResponse {
  id: string;
  name: string;
  gl_account_id: string;
  account_number: string | null;
  sort_code: string | null;
  currency: string;
}

export interface CreateBankAccountRequest {
  name: string;
  gl_account_id: string;
  account_number?: string | null;
  sort_code?: string | null;
  currency?: string;
}

export interface ImportLineModel {
  line_date?: string | null;
  description?: string;
  money_out_minor?: number;
  money_in_minor?: number;
  balance_minor?: number | null;
}

export interface ImportResultResponse {
  imported: number;
  duplicates: number;
}

export interface BankStatementLineResponse {
  id: string;
  line_date: string | null;
  description: string;
  money_out_minor: number;
  money_in_minor: number;
  balance_minor: number | null;
  is_posted: boolean;
}

export interface ReconcilableLineResponse {
  journal_line_id: string;
  journal_id: string;
  line_date: string | null;
  narrative: string | null;
  amount_minor: number;
  reconciled: boolean;
}

export interface ReconciliationSummaryResponse {
  ledger_balance_minor: number;
  reconciled_balance_minor: number;
  unreconciled_count: number;
  statement_balance_minor: number | null;
  difference_minor: number | null;
}

export interface MatchSuggestionResponse {
  journal_line_id: string;
  ledger_date: string | null;
  ledger_narrative: string | null;
  statement_line_id: string;
  statement_date: string | null;
  statement_description: string;
  amount_minor: number;
  confidence: 'exact' | 'amount';
  days_apart: number | null;
}

export interface VatReturnResponse {
  box1_minor: number;
  box2_minor: number;
  box3_minor: number;
  box4_minor: number;
  box5_minor: number;
  box6_minor: number;
  box7_minor: number;
  box8_minor: number;
  box9_minor: number;
}

export interface VatSubmissionResponse {
  id: string;
  period_start: string;
  period_end: string;
  reference: string;
  finalised_at: string;
  boxes: VatReturnResponse;
}

export type PeriodStatus = 'open' | 'soft_closed' | 'locked';

export interface PeriodResponse {
  id: string;
  fiscal_year: number;
  starts_on: string;
  ends_on: string;
  status: PeriodStatus;
}
