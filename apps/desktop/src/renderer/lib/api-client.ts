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
  DeviceResponse,
  LoginRequest,
  RegisterDeviceRequest,
  RegisterDeviceResponse,
  TokenResponse,
  UserResponse,
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
}
