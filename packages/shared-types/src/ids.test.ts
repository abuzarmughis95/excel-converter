import { describe, expect, it } from 'vitest';
import { asUuid, isUuid, isUuidV7 } from './ids.js';

describe('isUuid', () => {
  it('accepts a valid UUID', () => {
    expect(isUuid('018f4e2a-1b2c-7d3e-8f4a-5b6c7d8e9f01')).toBe(true);
  });

  it('rejects malformed strings', () => {
    expect(isUuid('not-a-uuid')).toBe(false);
    expect(isUuid('018f4e2a1b2c7d3e8f4a5b6c7d8e9f01')).toBe(false);
    expect(isUuid('')).toBe(false);
  });

  it('rejects non-string values', () => {
    expect(isUuid(123)).toBe(false);
    expect(isUuid(null)).toBe(false);
    expect(isUuid(undefined)).toBe(false);
  });
});

describe('isUuidV7', () => {
  it('accepts a UUIDv7 (version 7, RFC 4122 variant)', () => {
    expect(isUuidV7('018f4e2a-1b2c-7d3e-8f4a-5b6c7d8e9f01')).toBe(true);
    expect(isUuidV7('018f4e2a-1b2c-7d3e-bf4a-5b6c7d8e9f01')).toBe(true);
  });

  it('rejects a UUIDv4 (version 4)', () => {
    expect(isUuidV7('f47ac10b-58cc-4372-a567-0e02b2c3d479')).toBe(false);
  });

  it('rejects a v7 with an invalid variant nibble', () => {
    expect(isUuidV7('018f4e2a-1b2c-7d3e-0f4a-5b6c7d8e9f01')).toBe(false);
  });
});

describe('asUuid', () => {
  it('brands a valid UUID', () => {
    const id = asUuid('018f4e2a-1b2c-7d3e-8f4a-5b6c7d8e9f01');
    expect(id).toBe('018f4e2a-1b2c-7d3e-8f4a-5b6c7d8e9f01');
  });

  it('throws on an invalid UUID', () => {
    expect(() => asUuid('nope')).toThrow(TypeError);
  });
});
