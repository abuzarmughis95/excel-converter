import { useState, type FormEvent, type JSX } from 'react';

import { ApiError } from '../lib/api-client.js';
import { useAuth } from './AuthContext.js';

/**
 * Login form. Submits credentials to the backend via the auth context and
 * surfaces a friendly message on failure. On success the context flips to
 * authenticated and the app shell renders.
 */
export function LoginScreen(): JSX.Element {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 429
            ? 'Too many attempts. Please wait and try again.'
            : 'Invalid email or password.',
        );
      } else {
        setError('Could not reach the server. Is the backend running?');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <form
        className="login-card"
        onSubmit={(e) => {
          void onSubmit(e);
        }}
        aria-label="Sign in"
      >
        <h1 className="login-brand">Ledgerline</h1>
        <p className="login-subtitle">Sign in to continue</p>

        <label className="login-field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
            }}
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
            }}
          />
        </label>

        {error !== null && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="login-submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
