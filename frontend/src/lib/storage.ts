/**
 * Thin localStorage wrapper. Errors never bubble (silent-swallow policy).
 * No SSR guards — EchoLearn is a Vite SPA; try/catch handles unavailability.
 */

export function readString(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeString(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Silent-swallow: QuotaExceededError, SecurityError, etc.
  }
}

/**
 * Read + parse with fallback.
 * Returns `fallback` if the key is missing, the read throws, or `parse` returns null.
 */
export function readValidated<T>(
  key: string,
  parse: (raw: string) => T | null,
  fallback: T,
): T {
  const raw = readString(key);
  if (raw === null) return fallback;
  const parsed = parse(raw);
  return parsed === null ? fallback : parsed;
}
