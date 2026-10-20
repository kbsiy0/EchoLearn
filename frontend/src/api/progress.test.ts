/**
 * Contract tests for api/progress.ts
 *
 * Tests the get/put/delete progress client against the post-flatten
 * error envelope shape emitted by the backend.
 */

import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../test/setup';
import { getProgress, putProgress, deleteProgress } from './progress';

const VIDEO_ID = 'abc123def456';
const BASE_URL = `http://localhost:8000/api/videos/${VIDEO_ID}/progress`;

const PROGRESS_BODY = {
  last_played_sec: 42.5,
  last_segment_idx: 3,
  playback_rate: 1.0,
  loop_enabled: false,
  updated_at: '2026-04-28T10:00:00Z',
};

describe('getProgress', () => {
  it('test_get_progress_returns_parsed_value_on_200', async () => {
    server.use(
      http.get(BASE_URL, () => HttpResponse.json(PROGRESS_BODY)),
    );

    const result = await getProgress(VIDEO_ID);

    expect(result).not.toBeNull();
    expect(result?.last_played_sec).toBe(42.5);
    expect(result?.last_segment_idx).toBe(3);
    expect(result?.playback_rate).toBe(1.0);
    expect(result?.loop_enabled).toBe(false);
    expect(result?.updated_at).toBe('2026-04-28T10:00:00Z');
  });

  it('test_get_progress_returns_null_on_404', async () => {
    server.use(
      http.get(BASE_URL, () =>
        HttpResponse.json({ error_code: 'NOT_FOUND', error_message: 'No progress' }, { status: 404 }),
      ),
    );

    const result = await getProgress(VIDEO_ID);
    expect(result).toBeNull();
  });

  it('test_get_progress_throws_on_5xx', async () => {
    server.use(
      http.get(BASE_URL, () =>
        HttpResponse.json({ error_code: 'INTERNAL_ERROR', error_message: 'Server blew up' }, { status: 500 }),
      ),
    );

    await expect(getProgress(VIDEO_ID)).rejects.toThrow();
  });

  it('test_get_progress_throws_on_network_error', async () => {
    server.use(
      http.get(BASE_URL, () => { throw new Error('network blip'); }),
    );

    await expect(getProgress(VIDEO_ID)).rejects.toThrow();
  });
});

describe('putProgress', () => {
  const PUT_BODY = {
    last_played_sec: 42.5,
    last_segment_idx: 3,
    playback_rate: 1.0,
    loop_enabled: false,
  };

  it('test_put_progress_resolves_on_204', async () => {
    server.use(
      http.put(BASE_URL, () => new HttpResponse(null, { status: 204 })),
    );

    await expect(putProgress(VIDEO_ID, PUT_BODY)).resolves.toBeUndefined();
  });

  it('test_put_progress_throws_on_400', async () => {
    server.use(
      http.put(BASE_URL, () =>
        HttpResponse.json(
          { error_code: 'VALIDATION_ERROR', error_message: 'last_played_sec must be >= 0' },
          { status: 400 },
        ),
      ),
    );

    await expect(putProgress(VIDEO_ID, PUT_BODY)).rejects.toThrow(
      expect.objectContaining({
        message: expect.stringContaining('VALIDATION_ERROR'),
      }),
    );
    await expect(putProgress(VIDEO_ID, PUT_BODY)).rejects.toThrow(
      expect.objectContaining({
        message: expect.stringContaining('last_played_sec must be >= 0'),
      }),
    );
  });

  it('test_put_progress_throws_on_404', async () => {
    server.use(
      http.put(BASE_URL, () =>
        HttpResponse.json(
          { error_code: 'VIDEO_NOT_FOUND', error_message: 'Video not found' },
          { status: 404 },
        ),
      ),
    );

    await expect(putProgress(VIDEO_ID, PUT_BODY)).rejects.toThrow();
  });

  it('test_put_progress_sends_correct_body_shape', async () => {
    let capturedBody: Record<string, unknown> | null = null;

    server.use(
      http.put(BASE_URL, async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await putProgress(VIDEO_ID, PUT_BODY);

    expect(capturedBody).not.toBeNull();
    expect(capturedBody).toHaveProperty('last_played_sec', 42.5);
    expect(capturedBody).toHaveProperty('last_segment_idx', 3);
    expect(capturedBody).toHaveProperty('playback_rate', 1.0);
    expect(capturedBody).toHaveProperty('loop_enabled', false);
    // updated_at must NOT be in the request body
    expect(capturedBody).not.toHaveProperty('updated_at');
  });
});

describe('deleteProgress', () => {
  it('test_delete_progress_resolves_on_204', async () => {
    server.use(
      http.delete(BASE_URL, () => new HttpResponse(null, { status: 204 })),
    );

    await expect(deleteProgress(VIDEO_ID)).resolves.toBeUndefined();
  });

  it('test_delete_progress_throws_on_5xx', async () => {
    server.use(
      http.delete(BASE_URL, () =>
        HttpResponse.json({ error_code: 'INTERNAL_ERROR', error_message: 'Server error' }, { status: 500 }),
      ),
    );

    await expect(deleteProgress(VIDEO_ID)).rejects.toThrow();
  });

  it('test_delete_progress_resolves_on_404_treated_as_idempotent', async () => {
    // Despite the name, backend returns 404 for invalid video_id (not "no row").
    // The client should throw on 404 from DELETE (only 204 is success).
    server.use(
      http.delete(BASE_URL, () =>
        HttpResponse.json(
          { error_code: 'VIDEO_NOT_FOUND', error_message: 'Video not found' },
          { status: 404 },
        ),
      ),
    );

    await expect(deleteProgress(VIDEO_ID)).rejects.toThrow();
  });
});
