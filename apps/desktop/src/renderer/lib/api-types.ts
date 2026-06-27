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
