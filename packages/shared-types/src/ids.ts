/**
 * Branded identifier types.
 *
 * All syncable entities use UUIDv7 (time-ordered) identifiers so the desktop
 * client can mint globally-unique IDs while offline without collision risk on
 * sync. Branding prevents accidentally passing, e.g., a CompanyId where a
 * UserId is expected — a class of bug that is dangerous in multi-tenant
 * accounting software.
 */

declare const __brand: unique symbol;

type Brand<T, B extends string> = T & { readonly [__brand]: B };

export type Uuid = Brand<string, 'Uuid'>;
export type UserId = Brand<string, 'UserId'>;
export type OrgId = Brand<string, 'OrgId'>;
export type CompanyId = Brand<string, 'CompanyId'>;
export type DeviceId = Brand<string, 'DeviceId'>;
export type AccountId = Brand<string, 'AccountId'>;
export type JournalId = Brand<string, 'JournalId'>;
export type EventId = Brand<string, 'EventId'>;

/**
 * Matches the canonical RFC 4122 textual representation, case-insensitive.
 * Version/variant nibbles are validated separately by {@link isUuidV7}.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Type guard: is the value a syntactically valid UUID string? */
export function isUuid(value: unknown): value is Uuid {
  return typeof value === 'string' && UUID_RE.test(value);
}

/**
 * Type guard: is the value a UUIDv7 specifically (version nibble === 7 and
 * RFC 4122 variant)? Used to assert that minted IDs are time-ordered.
 */
export function isUuidV7(value: unknown): value is Uuid {
  if (!isUuid(value)) {
    return false;
  }
  const version = value.charAt(14);
  const variant = value.charAt(19).toLowerCase();
  return (
    version === '7' && (variant === '8' || variant === '9' || variant === 'a' || variant === 'b')
  );
}

/**
 * Assert-and-brand a raw string as a {@link Uuid}. Throws on malformed input
 * so invalid identifiers cannot silently propagate into the ledger.
 */
export function asUuid(value: string): Uuid {
  if (!isUuid(value)) {
    throw new TypeError(`Invalid UUID: ${JSON.stringify(value)}`);
  }
  return value;
}
