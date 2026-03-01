interface LoadingSpinnerProps {
  progress: number;
  status: string;
}

export function LoadingSpinner({ progress, status }: LoadingSpinnerProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-12">
      {/* Spinner */}
      <div className="w-10 h-10 border-4 border-gray-600 border-t-blue-400 rounded-full animate-spin" />

      {/* Progress bar */}
      <div className="w-64 bg-gray-700 rounded-full h-2 overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-300"
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>

      {/* Status text */}
      <p className="text-gray-400 text-sm">{status}</p>
    </div>
  );
}
