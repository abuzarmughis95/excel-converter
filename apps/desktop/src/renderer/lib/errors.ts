/**
 * Error-message helper.
 *
 * Screens repeatedly turn a caught error into a user-facing string: an ApiError
 * carries a server message worth showing; anything else falls back to a generic
 * line. Centralised so that logic lives in one place.
 */

import { ApiError } from './api-client.js';

/** The message from an ApiError, otherwise the given fallback. */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}
