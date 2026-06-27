/**
 * The typed IPC contract shared by the Electron main process and the preload
 * bridge. Keeping a single source of truth prevents the renderer and main from
 * drifting, and documents exactly which privileged operations the renderer may
 * invoke. The surface is intentionally narrow.
 */

/** Channels the renderer may invoke (request/response). */
export const IPC_INVOKE_CHANNELS = {
  /** Returns static app metadata (version, platform). No privileges required. */
  appInfo: 'app:info',
} as const;

export type IpcInvokeChannel = (typeof IPC_INVOKE_CHANNELS)[keyof typeof IPC_INVOKE_CHANNELS];

/** Response shape for the `app:info` channel. */
export interface AppInfo {
  readonly appVersion: string;
  readonly platform: NodeJS.Platform;
}

/**
 * The bridge API exposed on `window.ledgerline` in the renderer. Every method
 * is explicitly declared so the preload allow-list and renderer types match.
 */
export interface LedgerlineBridge {
  getAppInfo(): Promise<AppInfo>;
}
