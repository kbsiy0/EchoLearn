interface VideoPlayerProps {
  videoId: string;
  containerId?: string;
}

export function VideoPlayer({ videoId, containerId = 'yt-player' }: VideoPlayerProps) {
  return (
    <div data-testid="video-player" className="w-full aspect-video bg-black rounded-lg overflow-hidden">
      <div id={containerId} key={videoId} className="w-full h-full" />
    </div>
  );
}
