/**
 * Extract YouTube video ID from various URL formats.
 * Supports:
 *   - https://www.youtube.com/watch?v=VIDEO_ID
 *   - https://youtu.be/VIDEO_ID
 *   - https://www.youtube.com/embed/VIDEO_ID
 *   - https://www.youtube.com/v/VIDEO_ID
 */
export function extractVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?.*v=)([A-Za-z0-9_-]{11})/,
    /(?:youtu\.be\/)([A-Za-z0-9_-]{11})/,
    /(?:youtube\.com\/embed\/)([A-Za-z0-9_-]{11})/,
    /(?:youtube\.com\/v\/)([A-Za-z0-9_-]{11})/,
  ];

  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }

  return null;
}

/**
 * Dynamically load the YouTube IFrame API script.
 * Returns a promise that resolves when the API is ready.
 */
export function loadYouTubeAPI(): Promise<void> {
  return new Promise((resolve) => {
    if (window.YT && window.YT.Player) {
      resolve();
      return;
    }

    // If the script is already loading, wait for callback
    if (document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
      const check = setInterval(() => {
        if (window.YT && window.YT.Player) {
          clearInterval(check);
          resolve();
        }
      }, 100);
      return;
    }

    const prevCallback = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (prevCallback) prevCallback();
      resolve();
    };

    const script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(script);
  });
}
