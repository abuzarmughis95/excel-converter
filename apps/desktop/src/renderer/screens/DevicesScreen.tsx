import { useCallback, useEffect, useState, type JSX } from 'react';

import { useAuth } from '../auth/AuthContext.js';
import { ApiError } from '../lib/api-client.js';
import type { DeviceResponse } from '../lib/api-types.js';

/** Detect the current platform for the device record. */
function currentPlatform(): string {
  const ua = navigator.userAgent.toLowerCase();
  if (ua.includes('win')) {
    return 'win';
  }
  if (ua.includes('mac')) {
    return 'mac';
  }
  if (ua.includes('linux')) {
    return 'linux';
  }
  return 'web';
}

/** Generate a base64-encoded ECDSA public key for this device registration. */
async function generatePublicKeyB64(): Promise<string> {
  const keyPair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    true,
    ['sign', 'verify'],
  );
  const raw = await crypto.subtle.exportKey('spki', keyPair.publicKey);
  const bytes = new Uint8Array(raw);
  let binary = '';
  for (const b of bytes) {
    binary += String.fromCharCode(b);
  }
  return btoa(binary);
}

/**
 * Devices screen: lists the signed-in user's registered devices and lets them
 * register this device or revoke an existing one — exercising the authenticated
 * backend endpoints end-to-end.
 */
export function DevicesScreen(): JSX.Element {
  const { api } = useAuth();
  const [devices, setDevices] = useState<DeviceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<void> => {
    setError(null);
    try {
      setDevices(await api.listDevices());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load devices.');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onRegister(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const publicKey = await generatePublicKeyB64();
      await api.registerDevice({
        name: `This ${currentPlatform()} device`,
        platform: currentPlatform(),
        public_key_b64: publicKey,
      });
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to register device.');
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(deviceId: string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await api.revokeDevice(deviceId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to revoke device.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-live="polite">
      <div className="devices-toolbar">
        <button type="button" onClick={() => void onRegister()} disabled={busy}>
          Register this device
        </button>
      </div>

      {error !== null && (
        <p className="login-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p>Loading devices…</p>
      ) : devices.length === 0 ? (
        <p>No devices registered yet.</p>
      ) : (
        <table className="devices-table">
          <thead>
            <tr>
              <th>Node</th>
              <th>Name</th>
              <th>Platform</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {devices.map((d) => (
              <tr key={d.id}>
                <td>{d.node_id}</td>
                <td>{d.name}</td>
                <td>{d.platform}</td>
                <td>{d.revoked ? 'Revoked' : 'Active'}</td>
                <td>
                  {!d.revoked && (
                    <button type="button" onClick={() => void onRevoke(d.id)} disabled={busy}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
