import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

/**
 * In dev, Vite's HMR client needs inline scripts and a websocket connection,
 * which the strict production CSP forbids. This plugin swaps the index.html CSP
 * for a dev-only policy while the dev server is running. Production builds keep
 * the strict CSP authored in index.html untouched.
 */
function devCsp(): Plugin {
  const DEV_CSP =
    "default-src 'self'; " +
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
    "style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data:; " +
    "connect-src 'self' ws: http://127.0.0.1:8000 http://localhost:8000; " +
    "object-src 'none'; base-uri 'none'";
  return {
    name: 'ledgerline-dev-csp',
    apply: 'serve',
    transformIndexHtml(html) {
      return html.replace(
        /<meta\s+http-equiv="Content-Security-Policy"[^>]*>/,
        `<meta http-equiv="Content-Security-Policy" content="${DEV_CSP}" />`,
      );
    },
  };
}

/**
 * Vite builds the renderer (React) bundle. The Electron main and preload
 * processes are compiled separately by tsc (see tsconfig.main.json).
 */
export default defineConfig({
  root: '.',
  // Relative base so built asset URLs are './assets/...' rather than '/assets/...'.
  // Electron loads the renderer via file:// in packaged builds, where an absolute
  // '/assets' path would resolve against the filesystem root and fail to load.
  base: './',
  plugins: [react(), devCsp()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist/renderer',
    emptyOutDir: true,
    sourcemap: true,
  },
});
