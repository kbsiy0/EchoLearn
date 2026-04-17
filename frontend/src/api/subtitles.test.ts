/**
 * Contract tests for api/subtitles.ts
 *
 * Verifies the exact request shape sent to the backend, catching field name regressions.
 */

import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../test/setup';
import { createJob } from './subtitles';

describe('createJob', () => {
  it('createJob posts url field not youtube_url', async () => {
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.post('http://localhost:8000/api/subtitles/jobs', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          job_id: 'job-test-001',
          video_id: 'dQw4w9WgXcQ',
          status: 'queued',
        });
      }),
    );

    await createJob('https://www.youtube.com/watch?v=dQw4w9WgXcQ');

    expect(capturedBody).not.toBeNull();
    // Must use 'url' field — not 'youtube_url' or any other name
    expect(capturedBody).toHaveProperty('url', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    expect(capturedBody).not.toHaveProperty('youtube_url');
  });
});
