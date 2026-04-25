/**
 * Contract tests for api/subtitles.ts
 *
 * Verifies the exact request shape sent to the backend, catching field name regressions.
 */

import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../test/setup';
import { createJob, getSubtitles } from './subtitles';
import type { SubtitleResponse } from '../types/subtitle';

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

describe('getSubtitles', () => {
  const SEGMENTS = [
    {
      idx: 0,
      start: 0.0,
      end: 3.5,
      text_en: 'Hello world.',
      text_zh: '你好，世界。',
      words: [{ text: 'Hello', start: 0.0, end: 1.2 }, { text: 'world.', start: 1.4, end: 3.5 }],
    },
  ];

  it('test_get_subtitles_parses_completed_shape', async () => {
    server.use(
      http.get('http://localhost:8000/api/subtitles/vid-001', () =>
        HttpResponse.json({
          video_id: 'vid-001',
          status: 'completed',
          progress: 100,
          title: 'My Video',
          duration_sec: 180.5,
          segments: SEGMENTS,
          error_code: null,
          error_message: null,
        }),
      ),
    );

    const result: SubtitleResponse = await getSubtitles('vid-001');

    expect(result.video_id).toBe('vid-001');
    expect(result.status).toBe('completed');
    expect(result.progress).toBe(100);
    expect(result.title).toBe('My Video');
    expect(result.duration_sec).toBe(180.5);
    expect(result.segments).toHaveLength(1);
    expect(result.error_code).toBeNull();
    expect(result.error_message).toBeNull();
  });

  it('test_get_subtitles_parses_processing_shape', async () => {
    server.use(
      http.get('http://localhost:8000/api/subtitles/vid-002', () =>
        HttpResponse.json({
          video_id: 'vid-002',
          status: 'processing',
          progress: 32,
          title: 'Partial Video',
          duration_sec: 60.0,
          segments: SEGMENTS,
          error_code: null,
          error_message: null,
        }),
      ),
    );

    const result: SubtitleResponse = await getSubtitles('vid-002');

    expect(result.status).toBe('processing');
    expect(result.progress).toBe(32);
    expect(result.title).toBe('Partial Video');
    expect(result.error_code).toBeNull();
    expect(result.error_message).toBeNull();
    expect(result.segments).toHaveLength(1);
  });

  it('test_get_subtitles_parses_failed_shape', async () => {
    server.use(
      http.get('http://localhost:8000/api/subtitles/vid-003', () =>
        HttpResponse.json({
          video_id: 'vid-003',
          status: 'failed',
          progress: 0,
          title: null,
          duration_sec: null,
          segments: [],
          error_code: 'TRANSCRIPTION_FAILED',
          error_message: 'Whisper returned an error.',
        }),
      ),
    );

    const result: SubtitleResponse = await getSubtitles('vid-003');

    expect(result.status).toBe('failed');
    expect(result.progress).toBe(0);
    expect(result.title).toBeNull();
    expect(result.duration_sec).toBeNull();
    expect(result.segments).toHaveLength(0);
    expect(result.error_code).toBe('TRANSCRIPTION_FAILED');
    expect(result.error_message).toBe('Whisper returned an error.');
  });

  it('test_get_subtitles_parses_queued_shape_with_nulls', async () => {
    server.use(
      http.get('http://localhost:8000/api/subtitles/vid-004', () =>
        HttpResponse.json({
          video_id: 'vid-004',
          status: 'queued',
          progress: 0,
          title: null,
          duration_sec: null,
          segments: [],
          error_code: null,
          error_message: null,
        }),
      ),
    );

    const result: SubtitleResponse = await getSubtitles('vid-004');

    expect(result.status).toBe('queued');
    expect(result.progress).toBe(0);
    expect(result.title).toBeNull();
    expect(result.duration_sec).toBeNull();
    expect(result.segments).toHaveLength(0);
    expect(result.error_code).toBeNull();
    expect(result.error_message).toBeNull();
  });

  it('test_get_subtitles_404_surfaces_error', async () => {
    server.use(
      http.get('http://localhost:8000/api/subtitles/vid-not-found', () =>
        HttpResponse.json({ detail: 'Video not found' }, { status: 404 }),
      ),
    );

    await expect(getSubtitles('vid-not-found')).rejects.toThrow('404');
  });
});
