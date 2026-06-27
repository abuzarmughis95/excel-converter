/**
 * Renderer runtime configuration.
 *
 * The API base URL is injected at build time via Vite's `import.meta.env`. It
 * defaults to the local backend so a developer can run both without extra
 * configuration.
 */

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/v1';

/** Base URL of the backend API, without a trailing slash. */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  '',
);
