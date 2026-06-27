import { describe, expect, it } from 'vitest';
import {
  add,
  currency,
  equals,
  isZero,
  money,
  negate,
  sign,
  subtract,
  sum,
  zero,
} from './money.js';

describe('money construction', () => {
  it('constructs from integer minor units', () => {
    const m = money(12345, 'GBP');
    expect(m.minorUnits).toBe(12345);
    expect(m.currency).toBe('GBP');
  });

  it('rejects non-integer minor units (float drift guard)', () => {
    expect(() => money(10.5, 'GBP')).toThrow(TypeError);
  });

  it('rejects values beyond the safe integer range', () => {
    expect(() => money(Number.MAX_SAFE_INTEGER + 1, 'GBP')).toThrow();
  });

  it('rejects invalid currency codes', () => {
    expect(() => currency('gbp')).toThrow();
    expect(() => currency('POUND')).toThrow();
    expect(() => currency('G2P')).toThrow();
  });

  it('produces zero', () => {
    expect(isZero(zero('GBP'))).toBe(true);
  });
});

describe('money arithmetic', () => {
  it('adds same-currency values exactly (no float drift)', () => {
    // 0.1 + 0.2 in pence: 10 + 20 === 30, exactly.
    expect(add(money(10, 'GBP'), money(20, 'GBP')).minorUnits).toBe(30);
  });

  it('subtracts same-currency values', () => {
    expect(subtract(money(100, 'GBP'), money(30, 'GBP')).minorUnits).toBe(70);
  });

  it('negates', () => {
    expect(negate(money(500, 'GBP')).minorUnits).toBe(-500);
  });

  it('throws on currency mismatch in add', () => {
    expect(() => add(money(100, 'GBP'), money(100, 'USD'))).toThrow(/Currency mismatch/);
  });

  it('throws on currency mismatch in subtract', () => {
    expect(() => subtract(money(100, 'GBP'), money(100, 'EUR'))).toThrow(/Currency mismatch/);
  });
});

describe('money sum', () => {
  it('sums a list', () => {
    const total = sum([money(100, 'GBP'), money(250, 'GBP'), money(-50, 'GBP')]);
    expect(total.minorUnits).toBe(300);
  });

  it('returns zero for empty list with explicit currency', () => {
    expect(sum([], 'GBP').minorUnits).toBe(0);
  });

  it('throws on empty list without currency', () => {
    expect(() => sum([])).toThrow();
  });

  it('throws if list mixes currencies', () => {
    expect(() => sum([money(1, 'GBP'), money(1, 'USD')])).toThrow(/Currency mismatch/);
  });
});

describe('money predicates', () => {
  it('reports sign', () => {
    expect(sign(money(5, 'GBP'))).toBe(1);
    expect(sign(money(-5, 'GBP'))).toBe(-1);
    expect(sign(money(0, 'GBP'))).toBe(0);
  });

  it('compares equality including currency', () => {
    expect(equals(money(100, 'GBP'), money(100, 'GBP'))).toBe(true);
    expect(equals(money(100, 'GBP'), money(100, 'USD'))).toBe(false);
    expect(equals(money(100, 'GBP'), money(101, 'GBP'))).toBe(false);
  });
});
