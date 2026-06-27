/**
 * Electron main process entry point.
 *
 * Responsibilities at this stage (F-12): create a single hardened window, wire
 * the narrow IPC handler, and lock down navigation/window creation. The Python
 * sidecar and local database are introduced in Phase 3 (SY-01/SY-02).
 */

import path from 'node:path';

import { app, BrowserWindow, ipcMain, shell } from 'electron';

import { IPC_INVOKE_CHANNELS, type AppInfo } from '../shared/ipc-contract.js';
import { hardenedWebPreferences, isNavigationAllowed, shouldDenyWindowOpen } from './security.js';

// Compiled to CommonJS for Electron's main process; __dirname is provided by
// the CJS module wrapper. The renderer is built separately as ESM by Vite.

/** Dev server URL injected by Vite; absent in packaged builds. */
const DEV_SERVER_URL = process.env['ELECTRON_RENDERER_URL'];

function registerIpcHandlers(): void {
  ipcMain.handle(IPC_INVOKE_CHANNELS.appInfo, (): AppInfo => {
    return { appVersion: app.getVersion(), platform: process.platform };
  });
}

function applyNavigationGuards(window: BrowserWindow): void {
  window.webContents.on('will-navigate', (event, targetUrl) => {
    const currentUrl = window.webContents.getURL();
    if (!isNavigationAllowed(currentUrl, targetUrl)) {
      event.preventDefault();
    }
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (shouldDenyWindowOpen()) {
      // External links are opened in the OS browser, never a new Electron window.
      void shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
}

function createMainWindow(): BrowserWindow {
  const preloadPath = path.join(__dirname, '../preload/index.js');

  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    webPreferences: hardenedWebPreferences(preloadPath),
  });

  applyNavigationGuards(window);

  // Surface renderer load failures to the main-process log instead of failing
  // silently with a blank window.
  window.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    process.stderr.write(
      `[renderer] did-fail-load ${String(errorCode)} ${errorDescription} ${validatedURL}\n`,
    );
  });
  window.webContents.on('render-process-gone', (_event, details) => {
    process.stderr.write(`[renderer] process gone: ${details.reason}\n`);
  });

  window.once('ready-to-show', () => {
    window.show();
    // Smoke mode: used by packaging/CI to prove the app boots end-to-end
    // (main → window → renderer ready) then exits cleanly with code 0.
    if (process.env['LEDGERLINE_SMOKE'] === '1') {
      app.quit();
    }
  });

  if (DEV_SERVER_URL !== undefined && DEV_SERVER_URL !== '') {
    void window.loadURL(DEV_SERVER_URL);
  } else {
    void window.loadFile(path.join(__dirname, '../renderer/index.html'));
  }

  return window;
}

void app.whenReady().then(() => {
  registerIpcHandlers();
  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
