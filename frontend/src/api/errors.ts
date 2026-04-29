/**
 * Shared 4xx/5xx body-parser used by API clients that share the canonical
 * `{error_code, error_message}` envelope (after main.py's flatten).
 *
 * Throws an Error whose message is `${code}: ${msg}` so callers can grep
 * either the code or the human reason.
 */
export async function throwTypedError(res: Response): Promise<never> {
  const parsed = (await res.json().catch(() => ({}))) as Record<string, string>;
  const code = parsed.error_code ?? '';
  const msg = parsed.error_message ?? `HTTP ${res.status}`;
  throw new Error(`${code}: ${msg}`);
}
