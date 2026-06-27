/**
 * Centralised Electron security hardening.
 *
 * These defaults are mandatory for commercial software handling financial data:
 * the renderer runs untrusted-by-default with no Node integration, context
 * isolation on, and navigation/window-open locked down. Encoded here (and
 * unit-tested) so a future change cannot silently weaken them.
 */

import type { WebPreferences } from 'electron';

/** Hardened WebPreferences applied to every BrowserWindow. */
export function hardenedWebPreferences(preloadPath: string): WebPreferences {
  return {
    preload: preloadPath,
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
    allowRunningInsecureContent: false,
    experimentalFeatures: false,
  };
}

/**
 * Whether navigation to `targetUrl` is permitted from a page currently at
 * `currentUrl`. Only same-origin (or, in dev, the local Vite server) is allowed;
 * everything else is blocked to prevent the renderer being navigated to a
 * hostile origin.
 */
export function isNavigationAllowed(currentUrl: string, targetUrl: string): boolean {
  let current: URL;
  let target: URL;
  try {
    current = new URL(currentUrl);
    target = new URL(targetUrl);
  } catch {
    return false;
  }
  return current.origin === target.origin;
}

/**
 * `window.open` is never permitted from the renderer; external links must be
 * routed through a vetted handler. Always denies.
 */
export function shouldDenyWindowOpen(): boolean {
  return true;
}
