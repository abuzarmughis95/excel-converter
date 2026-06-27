import type { LedgerlineBridge } from '../shared/ipc-contract.js';

declare global {
  interface Window {
    /** Exposed by the preload bridge. Present only in the Electron renderer. */
    readonly ledgerline: LedgerlineBridge;
  }
}

export {};
