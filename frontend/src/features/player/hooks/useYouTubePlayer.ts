import { useEffect, useRef, useState, useCallback } from 'react';
import { loadYouTubeAPI } from '../../../lib/youtube';

interface UseYouTubePlayerReturn {
  player: YT.Player | null;
  isReady: boolean;
  currentTime: number;
  playerState: number;
  seekTo: (seconds: number) => void;
  playVideo: () => void;
  pauseVideo: () => void;
}

export function useYouTubePlayer(
  videoId: string | null,
  containerId: string
): UseYouTubePlayerReturn {
  const playerRef = useRef<YT.Player | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [playerState, setPlayerState] = useState(-1);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Create / destroy player when videoId changes
  useEffect(() => {
    if (!videoId) return;

    let destroyed = false;

    const createPlayer = async () => {
      await loadYouTubeAPI();
      if (destroyed) return;

      // Destroy previous player
      if (playerRef.current) {
        playerRef.current.destroy();
        playerRef.current = null;
      }

      // Wait for container element to appear in DOM
      const waitForContainer = (): Promise<HTMLElement> => {
        return new Promise((resolve) => {
          const el = document.getElementById(containerId);
          if (el) {
            resolve(el);
            return;
          }
          const observer = new MutationObserver(() => {
            const el = document.getElementById(containerId);
            if (el) {
              observer.disconnect();
              resolve(el);
            }
          });
          observer.observe(document.body, { childList: true, subtree: true });
        });
      };

      await waitForContainer();
      if (destroyed) return;

      playerRef.current = new YT.Player(containerId, {
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
    };

    setIsReady(false);
    setCurrentTime(0);
    setPlayerState(-1);
    createPlayer();

    return () => {
      destroyed = true;
      if (playerRef.current) {
        playerRef.current.destroy();
        playerRef.current = null;
      }
      setIsReady(false);
    };
  }, [videoId, containerId]);

  // Polling for currentTime (100ms)
  useEffect(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }

    if (!isReady || !playerRef.current) return;

    pollingRef.current = setInterval(() => {
      if (playerRef.current && typeof playerRef.current.getCurrentTime === 'function') {
        setCurrentTime(playerRef.current.getCurrentTime());
      }
    }, 100);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [isReady]);

  const seekTo = useCallback((seconds: number) => {
    playerRef.current?.seekTo(seconds, true);
  }, []);

  const playVideo = useCallback(() => {
    playerRef.current?.playVideo();
  }, []);

  const pauseVideo = useCallback(() => {
    playerRef.current?.pauseVideo();
  }, []);

  /* eslint-disable react-hooks/refs */
  return {
    player: playerRef.current,
    isReady,
    currentTime,
    playerState,
    seekTo,
    playVideo,
    pauseVideo,
  };
  /* eslint-enable react-hooks/refs */
}
