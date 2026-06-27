/**
 * Money as integer minor units (e.g. pence) plus an ISO-4217 currency code.
 *
 * Accounting software MUST NOT use floating-point for money: 0.1 + 0.2 !== 0.3
 * in IEEE-754, and such drift is catastrophic in a ledger. All amounts are
 * stored and manipulated as integer minor units. Division/percentage results
 * (VAT, FX) are rounded exactly once, via an explicitly named policy, at the
 * point of computation — never re-derived differently downstream.
 *
 * This is the TypeScript-side mirror of the authoritative Python engine's
 * `Money` type. It deliberately provides ONLY exact integer operations (add,
 * subtract, sum, sign) for transport and display. Division, percentage, FX, and
 * any rounding live exclusively in the Python accounting engine
 * (`ledgerline_engine.money`) so there is a single source of truth for the
 * numbers — the renderer never computes VAT or rounds money itself.
 */

export type CurrencyCode = string & { readonly __currency: unique symbol };

export interface Money {
  /** Amount in integer minor units. May be negative. */
  readonly minorUnits: number;
  /** ISO-4217 alphabetic code, uppercase (e.g. "GBP"). */
  readonly currency: CurrencyCode;
}

const CURRENCY_RE = /^[A-Z]{3}$/;

/** Validate and brand an ISO-4217 currency code. */
export function currency(code: string): CurrencyCode {
  if (!CURRENCY_RE.test(code)) {
    throw new TypeError(`Invalid ISO-4217 currency code: ${JSON.stringify(code)}`);
  }
  return code as CurrencyCode;
}

/** Construct Money from integer minor units. Rejects non-integers (drift guard). */
export function money(minorUnits: number, code: string): Money {
  if (!Number.isInteger(minorUnits)) {
    throw new TypeError(`Money minor units must be an integer, received: ${String(minorUnits)}`);
  }
  if (!Number.isSafeInteger(minorUnits)) {
    throw new RangeError(`Money minor units exceed safe integer range: ${String(minorUnits)}`);
  }
  return { minorUnits, currency: currency(code) };
}

/** Zero in the given currency. */
export function zero(code: string): Money {
  return money(0, code);
}

function assertSameCurrency(a: Money, b: Money): void {
  if (a.currency !== b.currency) {
    throw new TypeError(`Currency mismatch: ${a.currency} vs ${b.currency}`);
  }
}

/** Add two Money values of the same currency. */
export function add(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.minorUnits + b.minorUnits, a.currency);
}

/** Subtract b from a (same currency). */
export function subtract(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.minorUnits - b.minorUnits, a.currency);
}

/** Negate a Money value. */
export function negate(a: Money): Money {
  return money(-a.minorUnits, a.currency);
}

/** Sum a list of Money values; an empty list requires an explicit currency. */
export function sum(values: readonly Money[], currencyIfEmpty?: string): Money {
  if (values.length === 0) {
    if (currencyIfEmpty === undefined) {
      throw new TypeError('Cannot sum an empty list without an explicit currency');
    }
    return zero(currencyIfEmpty);
  }
  return values.reduce((acc, v) => add(acc, v));
}

export type Sign = -1 | 0 | 1;

/** Sign of a Money value: -1, 0, or 1. */
export function sign(a: Money): Sign {
  if (a.minorUnits > 0) {
    return 1;
  }
  if (a.minorUnits < 0) {
    return -1;
  }
  return 0;
}

export function isZero(a: Money): boolean {
  return a.minorUnits === 0;
}

export function equals(a: Money, b: Money): boolean {
  return a.currency === b.currency && a.minorUnits === b.minorUnits;
}
