import { useCallback, useEffect, useRef, useState } from 'react';
import { loadYouTubeAPI } from '../../../lib/youtube';

export interface UseYouTubePlayerReturn {
  player: YT.Player | null;
  isReady: boolean;
  playerState: number;
  seekTo: (seconds: number) => void;
  playVideo: () => void;
  pauseVideo: () => void;
}

/**
 * Manages the YouTube IFrame API lifecycle only.
 * - Creates/destroys player when videoId changes.
 * - Exposes player instance + isReady + playerState.
 * - Does NOT do any subtitle or time-tracking logic.
 *
 * Signature per specs/sync.md:
 *   useYouTubePlayer(videoId, containerId) → { player, isReady, playerState, seekTo, playVideo, pauseVideo }
 */
export function useYouTubePlayer(
  videoId: string | null,
  containerId: string,
): UseYouTubePlayerReturn {
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
        playerVars: {
          autoplay: 0,
          controls: 1,
          modestbranding: 1,
          rel: 0,
          origin: window.location.origin,
        },
        events: {
          onReady: () => {
            if (!destroyed) setIsReady(true);
          },
          onStateChange: (event: YT.OnStateChangeEvent) => {
            if (!destroyed) setPlayerState(event.data);
          },
        },
      });

      if (!destroyed) {
        setPlayer(p);
        destroyRef.current = () => p.destroy();
      }
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsReady(false);
    setPlayerState(-1);
    setPlayer(null);

    // If YT API is already loaded (common in tests and re-mounts), init synchronously.
    // Otherwise load the IFrame API script and wait for it.
    if (window.YT && window.YT.Player) {
      initPlayer();
    } else {
      loadYouTubeAPI().then(initPlayer);
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
