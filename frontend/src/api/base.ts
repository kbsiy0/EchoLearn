/**
 * Shared API base URL.
 * Override via VITE_API_BASE env var in production deployments.
 */
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000/api';
