import { describe, expect, it, vi } from 'vitest';

import { ApiClient, ApiError } from './api-client.js';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const BASE = 'http://test.local/v1';

describe('ApiClient', () => {
  it('sends JSON and parses the response', async () => {
    const fetchFn = vi.fn(async () => Promise.resolve(jsonResponse(200, { ok: true })));
    const client = new ApiClient({ getAccessToken: () => null, baseUrl: BASE, fetchFn });

    const result = await client.login({ email: 'a@b.com', password: 'pw' });

    expect(result).toEqual({ ok: true });
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}/auth/login`);
    expect(init.method).toBe('POST');
  });

  it('attaches the bearer token on authenticated requests', async () => {
    const fetchFn = vi.fn(async () => Promise.resolve(jsonResponse(200, { id: '1' })));
    const client = new ApiClient({ getAccessToken: () => 'tok', baseUrl: BASE, fetchFn });

    await client.me();

    const [, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer tok');
  });

  it('throws a typed ApiError with the server detail', async () => {
    const fetchFn = vi.fn(async () =>
      Promise.resolve(jsonResponse(401, { detail: 'Invalid email or password' })),
    );
    const client = new ApiClient({ getAccessToken: () => null, baseUrl: BASE, fetchFn });

    await expect(client.login({ email: 'a@b.com', password: 'x' })).rejects.toMatchObject({
      status: 401,
      message: 'Invalid email or password',
    });
  });

  it('refreshes once on a 401 then retries successfully', async () => {
    let call = 0;
    const fetchFn = vi.fn(async () => {
      call += 1;
      // First authenticated call 401s; after refresh, the retry succeeds.
      return Promise.resolve(call === 1 ? jsonResponse(401, { detail: 'expired' }) : jsonResponse(200, { id: '1' }));
    });
    const refreshSession = vi.fn(async () => Promise.resolve('new-token'));
    const client = new ApiClient({
      getAccessToken: () => 'old-token',
      refreshSession,
      baseUrl: BASE,
      fetchFn,
    });

    const result = await client.me();

    expect(result).toEqual({ id: '1' });
    expect(refreshSession).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it('does not retry when refresh fails', async () => {
    const fetchFn = vi.fn(async () => Promise.resolve(jsonResponse(401, { detail: 'expired' })));
    const refreshSession = vi.fn(async () => Promise.resolve(null));
    const client = new ApiClient({
      getAccessToken: () => 'old-token',
      refreshSession,
      baseUrl: BASE,
      fetchFn,
    });

    await expect(client.me()).rejects.toBeInstanceOf(ApiError);
    expect(refreshSession).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it('returns undefined for a 204 response', async () => {
    const fetchFn = vi.fn(async () => Promise.resolve(new Response(null, { status: 204 })));
    const client = new ApiClient({ getAccessToken: () => 'tok', baseUrl: BASE, fetchFn });

    await expect(client.revokeDevice('dev-1')).resolves.toBeUndefined();
  });
});
