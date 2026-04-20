/**
 * Vitest global setup — MSW server lifecycle only.
 *
 * No default handlers are registered here. Each test that needs MSW intercepts
 * defines its own handlers via server.use(...) to keep tests hermetic.
 *
 * Per spec: "MSW handlers are defined per test; there are no default handlers
 * in setup.ts beyond server lifecycle."
 */
import '@testing-library/jest-dom';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll } from 'vitest';

export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
