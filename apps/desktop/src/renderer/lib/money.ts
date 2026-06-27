/**
 * Money formatting/parsing in integer minor units (pence).
 *
 * The backend and engine speak integer minor units; these helpers convert to
 * and from the human "1234.56" form. Centralised so every screen formats money
 * identically. Never use floats for the amounts themselves — only for display.
 */

/** Format minor units as a £-prefixed string, e.g. -12345 -> "£-123.45". */
export function money(minor: number): string {
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  return `£${sign}${Math.trunc(abs / 100).toString()}.${(abs % 100).toString().padStart(2, '0')}`;
}

/**
 * Format minor units as a plain "123.45" string (no currency symbol).
 * With `blankZero`, returns '' for 0 — handy for sparse table cells.
 * A null amount always renders as ''.
 */
export function formatMinorPlain(
  minor: number | null,
  options: { blankZero?: boolean } = {},
): string {
  if (minor === null) {
    return '';
  }
  if (options.blankZero === true && minor === 0) {
    return '';
  }
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  return `${sign}${Math.trunc(abs / 100).toString()}.${(abs % 100).toString().padStart(2, '0')}`;
}

/**
 * Parse a "1234.56" string into non-negative minor units.
 * Returns 0 for empty input and NaN for anything malformed (callers guard on
 * Number.isNaN before posting).
 */
export function parseMajorToMinor(input: string): number {
  const cleaned = input.trim().replace(/,/g, '');
  if (cleaned === '') {
    return 0;
  }
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) {
    return Number.NaN;
  }
  const [whole, frac = ''] = cleaned.split('.');
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'));
}

/**
 * Parse a possibly-signed "1234.56" balance (tolerating £, commas, spaces) into
 * minor units, or null if blank/malformed.
 */
export function parseMajorToMinorOrNull(input: string): number | null {
  const cleaned = input.trim().replace(/[,£\s]/g, '');
  if (cleaned === '') {
    return null;
  }
  if (!/^-?\d+(\.\d{1,2})?$/.test(cleaned)) {
    return null;
  }
  const negative = cleaned.startsWith('-');
  const unsigned = negative ? cleaned.slice(1) : cleaned;
  const [whole, frac = ''] = unsigned.split('.');
  const minor = Number(whole) * 100 + Number(frac.padEnd(2, '0'));
  return negative ? -minor : minor;
}
