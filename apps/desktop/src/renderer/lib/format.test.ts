import { describe, expect, it } from 'vitest';
import { money } from '@ledgerline/shared-types';

import { formatDate, formatMoney, parseMoneyInput } from './format.js';

describe('formatMoney', () => {
  it('formats positive amounts', () => {
    expect(formatMoney(money(123456, 'GBP'))).toBe('£1,234.56');
  });

  it('formats zero', () => {
    expect(formatMoney(money(0, 'GBP'))).toBe('£0.00');
  });

  it('formats negative amounts', () => {
    expect(formatMoney(money(-50, 'GBP'))).toBe('-£0.50');
  });

  it('pads single-digit pence', () => {
    expect(formatMoney(money(105, 'GBP'))).toBe('£1.05');
  });
});

describe('parseMoneyInput', () => {
  it('parses a plain decimal to minor units', () => {
    expect(parseMoneyInput('1234.56')).toBe(123456);
  });

  it('parses thousands separators and currency symbols', () => {
    expect(parseMoneyInput('£1,234.56')).toBe(123456);
  });

  it('parses whole numbers', () => {
    expect(parseMoneyInput('100')).toBe(10000);
  });

  it('parses one-decimal input', () => {
    expect(parseMoneyInput('1.5')).toBe(150);
  });

  it('parses negatives', () => {
    expect(parseMoneyInput('-12.34')).toBe(-1234);
  });

  it('rejects fractional pence (three decimals)', () => {
    expect(() => parseMoneyInput('1.234')).toThrow(TypeError);
  });

  it('rejects non-numeric input', () => {
    expect(() => parseMoneyInput('abc')).toThrow(TypeError);
  });
});

describe('formatDate', () => {
  it('formats an ISO date without timezone drift', () => {
    expect(formatDate('2026-01-31')).toBe('31 Jan 2026');
  });

  it('rejects malformed dates', () => {
    expect(() => formatDate('31/01/2026')).toThrow(TypeError);
  });
});
