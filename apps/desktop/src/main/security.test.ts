import { describe, expect, it } from 'vitest';

import { hardenedWebPreferences, isNavigationAllowed, shouldDenyWindowOpen } from './security.js';

describe('hardenedWebPreferences', () => {
  it('enforces the mandatory security flags', () => {
    const prefs = hardenedWebPreferences('/path/to/preload.js');
    expect(prefs.contextIsolation).toBe(true);
    expect(prefs.nodeIntegration).toBe(false);
    expect(prefs.sandbox).toBe(true);
    expect(prefs.webSecurity).toBe(true);
    expect(prefs.allowRunningInsecureContent).toBe(false);
    expect(prefs.preload).toBe('/path/to/preload.js');
  });
});

describe('isNavigationAllowed', () => {
  it('allows same-origin navigation', () => {
    expect(isNavigationAllowed('http://localhost:5173/a', 'http://localhost:5173/b')).toBe(true);
  });

  it('blocks cross-origin navigation', () => {
    expect(isNavigationAllowed('http://localhost:5173/', 'https://evil.example/')).toBe(false);
  });

  it('blocks navigation to a different port (different origin)', () => {
    expect(isNavigationAllowed('http://localhost:5173/', 'http://localhost:9999/')).toBe(false);
  });

  it('returns false for malformed URLs', () => {
    expect(isNavigationAllowed('not-a-url', 'also-not')).toBe(false);
  });
});

describe('shouldDenyWindowOpen', () => {
  it('always denies renderer-initiated window.open', () => {
    expect(shouldDenyWindowOpen()).toBe(true);
  });
});
