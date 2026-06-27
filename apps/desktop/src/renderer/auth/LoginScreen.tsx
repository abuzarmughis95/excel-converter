import { useState, type JSX } from 'react';

import { Button, Form, TextField } from '../components/ui/index.js';
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

  async function onSubmit(): Promise<void> {
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
      <Form
        className="login-card"
        aria-label="Sign in"
        onSubmit={() => {
          void onSubmit();
        }}
      >
        <h1 className="login-brand">Ledgerline</h1>
        <p className="login-subtitle">Sign in to continue</p>

        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onValueChange={setEmail}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onValueChange={setPassword}
        />

        {error !== null && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}

        <Button type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </Form>
    </div>
  );
}
