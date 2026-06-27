/**
 * Preload bridge.
 *
 * Runs in an isolated context with access to a minimal Node surface. It exposes
 * ONLY the explicitly-listed methods of {@link LedgerlineBridge} on
 * `window.ledgerline` via contextBridge — never `ipcRenderer` itself. This is
 * the single trust boundary between the untrusted renderer and the main process.
 */

import { contextBridge, ipcRenderer } from 'electron';

import {
  IPC_INVOKE_CHANNELS,
  type AppInfo,
  type LedgerlineBridge,
} from '../shared/ipc-contract.js';

const bridge: LedgerlineBridge = {
  getAppInfo(): Promise<AppInfo> {
    return ipcRenderer.invoke(IPC_INVOKE_CHANNELS.appInfo) as Promise<AppInfo>;
  },
};

contextBridge.exposeInMainWorld('ledgerline', bridge);
