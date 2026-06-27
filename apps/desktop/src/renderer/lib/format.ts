/**
 * Presentation formatters for money and dates.
 *
 * Money is always received as integer minor units from the engine; this module
 * formats it for display without ever doing float arithmetic on the value.
 * Parsing rejects fractional pence so a malformed display value cannot become a
 * posting.
 */

import type { Money } from '@ledgerline/shared-types';

/**
 * Format Money (integer minor units) as a localized currency string.
 * Assumes a 2-decimal currency; the minor/major conversion is integer-based.
 */
export function formatMoney(value: Money, locale = 'en-GB'): string {
  const major = Math.trunc(value.minorUnits / 100);
  const minor = Math.abs(value.minorUnits % 100);
  // Reconstruct the decimal as a string to avoid float representation.
  const sign = value.minorUnits < 0 && major === 0 ? '-' : '';
  const decimal = `${sign}${String(major)}.${minor.toString().padStart(2, '0')}`;
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: value.currency,
  }).format(Number(decimal));
}

/**
 * Parse a user-entered amount (e.g. "1,234.56") into integer minor units.
 * Throws on more than two decimal places — fractional pence are not postable.
 */
export function parseMoneyInput(input: string): number {
  const cleaned = input.replace(/[,\s]/g, '').replace(/[£$€]/g, '');
  if (!/^-?\d+(\.\d{1,2})?$/.test(cleaned)) {
    throw new TypeError(`Invalid money input: ${JSON.stringify(input)}`);
  }
  const negative = cleaned.startsWith('-');
  const unsigned = negative ? cleaned.slice(1) : cleaned;
  const [whole, fraction = ''] = unsigned.split('.');
  const minor = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  return negative ? -minor : minor;
}

/** Format an ISO date string (YYYY-MM-DD) as a localized date. */
export function formatDate(isoDate: string, locale = 'en-GB'): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) {
    throw new TypeError(`Invalid ISO date: ${JSON.stringify(isoDate)}`);
  }
  const [year, month, day] = isoDate.split('-').map(Number) as [number, number, number];
  // Construct in UTC to avoid timezone shifting the calendar date.
  const date = new Date(Date.UTC(year, month - 1, day));
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}
