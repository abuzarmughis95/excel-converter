import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider, applyStoredThemeEarly, useTheme } from './ThemeContext.js';

function Harness(): JSX.Element {
  const { preference, resolved, toggle, setPreference } = useTheme();
  return (
    <div>
      <span data-testid="pref">{preference}</span>
      <span data-testid="resolved">{resolved}</span>
      <button type="button" onClick={toggle}>
        toggle
      </button>
      <button
        type="button"
        onClick={() => {
          setPreference('system');
        }}
      >
        system
      </button>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  // Default the matchMedia mock to "light".
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ThemeContext', () => {
  it('defaults to system (light here) and sets no data-theme', () => {
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('pref').textContent).toBe('system');
    expect(screen.getByTestId('resolved').textContent).toBe('light');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('toggles to dark, applies data-theme, and persists', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'toggle' }));

    expect(screen.getByTestId('resolved').textContent).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem('ledgerline.theme')).toBe('dark');
  });

  it('applyStoredThemeEarly restores a stored dark preference', () => {
    localStorage.setItem('ledgerline.theme', 'dark');
    applyStoredThemeEarly();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('system preference removes the data-theme attribute', async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );
    // Go dark, then back to system.
    await user.click(screen.getByRole('button', { name: 'toggle' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    await user.click(screen.getByRole('button', { name: 'system' }));
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});
