/**
 * PLACEHOLDER — DO NOT import from production code.
 *
 * This file exists ONLY in T01 so that useYouTubePlayer.test.ts can compile
 * and run against a controllable stub before the real hook is rewritten in T07.
 *
 * When T07 rewrites the hook, this placeholder MUST be deleted as part of
 * that same task (per spec invariant).
 *
 * ESLint guard: eslint.config.js has a no-restricted-imports rule preventing
 * files outside src/test/ (and non-test files) from importing anything from
 * src/test/placeholders/.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseYouTubePlayerReturn {
  player: YT.Player | null;
  isReady: boolean;
  playerState: number;
  seekTo: (seconds: number) => void;
  playVideo: () => void;
  pauseVideo: () => void;
}

/**
 * Placeholder implementation matching the spec signature from sync.md:
 *   useYouTubePlayer(videoId: string | null, containerId: string)
 *   → { player, isReady, playerState, seekTo, playVideo, pauseVideo }
 *
 * This placeholder wires up the YT.Player IFrame API lifecycle:
 * onReady → isReady = true, onStateChange → playerState updates.
 */
export function useYouTubePlayer(
  videoId: string | null,
  containerId: string,
): UseYouTubePlayerReturn {
  // Use state for player so returning it during render doesn't trigger ref access warning
  const [player, setPlayer] = useState<YT.Player | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [playerState, setPlayerState] = useState(-1);
  const destroyRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!videoId) return;
    let destroyed = false;

    const initPlayer = () => {
      if (destroyed) return;
      const p = new YT.Player(containerId, {
        videoId,
        events: {
          onReady: () => {
            if (!destroyed) setIsReady(true);
          },
          onStateChange: (event: YT.OnStateChangeEvent) => {
            if (!destroyed) setPlayerState(event.data);
          },
        },
      });
      if (!destroyed) setPlayer(p);
      destroyRef.current = () => p.destroy();
    };

    if (window.YT && window.YT.Player) {
      initPlayer();
    } else {
      (window as unknown as Record<string, unknown>)['onYouTubeIframeAPIReady'] = initPlayer;
    }

    return () => {
      destroyed = true;
      destroyRef.current?.();
      destroyRef.current = null;
      setPlayer(null);
      setIsReady(false);
      setPlayerState(-1);
    };
  }, [videoId, containerId]);

  const seekTo = useCallback((seconds: number) => {
    player?.seekTo(seconds, true);
  }, [player]);

  const playVideo = useCallback(() => {
    player?.playVideo();
  }, [player]);

  const pauseVideo = useCallback(() => {
    player?.pauseVideo();
  }, [player]);

  return { player, isReady, playerState, seekTo, playVideo, pauseVideo };
}
