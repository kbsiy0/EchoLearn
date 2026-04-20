/**
 * Tests for lib/storage.ts — thin localStorage wrapper with silent-swallow policy.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readString, readValidated, writeString } from './storage';

describe('storage', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Happy path ─────────────────────────────────────────────────────────────

  it('readString returns null when key is missing', () => {
    expect(readString('missing.key')).toBeNull();
  });

  it('readString returns stored value', () => {
    localStorage.setItem('test.key', 'hello');
    expect(readString('test.key')).toBe('hello');
  });

  it('writeString persists a value readable by readString', () => {
    writeString('test.key', 'world');
    expect(localStorage.getItem('test.key')).toBe('world');
  });

  // ── Mandatory: error-swallow behaviour ─────────────────────────────────────

  it('test_read_returns_null_when_storage_throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError', 'SecurityError');
    });
    let result: string | null = 'sentinel';
    expect(() => {
      result = readString('any.key');
    }).not.toThrow();
    expect(result).toBeNull();
  });

  it('test_write_swallows_quota_exceeded', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError', 'QuotaExceededError');
    });
    const consoleSpy = vi.spyOn(console, 'error');
    expect(() => {
      writeString('any.key', 'value');
    }).not.toThrow();
    expect(consoleSpy).not.toHaveBeenCalled();
  });

  it('test_read_validated_falls_back_on_invalid', () => {
    localStorage.setItem('test.rate', '0.6');
    const parse = (raw: string): number | null => {
      const n = parseFloat(raw);
      return [0.5, 0.75, 1, 1.25, 1.5].includes(n) ? n : null;
    };
    const result = readValidated('test.rate', parse, 1);
    expect(result).toBe(1);
  });

  it('readValidated returns fallback when key is missing', () => {
    const parse = (raw: string): number | null => parseFloat(raw) || null;
    expect(readValidated('missing.key', parse, 99)).toBe(99);
  });

  it('readValidated returns parsed value when valid', () => {
    localStorage.setItem('test.rate', '0.75');
    const parse = (raw: string): number | null => {
      const n = parseFloat(raw);
      return [0.5, 0.75, 1, 1.25, 1.5].includes(n) ? n : null;
    };
    expect(readValidated('test.rate', parse, 1)).toBe(0.75);
  });
});
