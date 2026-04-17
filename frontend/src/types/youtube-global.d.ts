/**
 * Window augmentation for YouTube IFrame API globals not covered by @types/youtube.
 * The `onYouTubeIframeAPIReady` callback is set on window to signal when the
 * IFrame API script has loaded.
 */
interface Window {
  onYouTubeIframeAPIReady?: () => void;
}
