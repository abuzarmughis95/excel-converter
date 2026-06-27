import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App.js';

/** A fetch stub that maps backend routes to canned JSON responses. */
function stubFetch(): void {
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = input instanceof URL ? input.href : String(input);
    if (url.endsWith('/auth/login')) {
      return jsonResponse(200, {
        access_token: 'access-token',
        refresh_token: 'refresh-token',
        token_type: 'bearer',
        expires_in: 900,
        mfa_required: false,
      });
    }
    if (url.endsWith('/auth/me')) {
      return jsonResponse(200, {
        id: '00000000-0000-7000-8000-000000000000',
        email: 'user@example.com',
        display_name: 'User',
        status: 'active',
      });
    }
    if (url.endsWith('/auth/devices')) {
      return jsonResponse(200, []);
    }
    if (url.endsWith('/companies')) {
      return jsonResponse(200, []);
    }
    return jsonResponse(404, { detail: 'not found' });
  });
  vi.stubGlobal('fetch', fetchMock);
}

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

beforeEach(() => {
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('shows the login screen when unauthenticated', () => {
    render(<App />);
    expect(screen.getByRole('form', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    // The app shell navigation is not shown before login.
    expect(screen.queryByRole('button', { name: 'Bookkeeping' })).not.toBeInTheDocument();
  });

  it('signs in and renders the app shell', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText('Email'), 'user@example.com');
    await user.type(screen.getByLabelText('Password'), 'password123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Bookkeeping' })).toBeInTheDocument();
    });
    expect(screen.getByText('user@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('shows an error on invalid credentials', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: 'Invalid email or password' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' },
          }),
        ),
      ),
    );
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText('Email'), 'user@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password.');
    });
  });
});
