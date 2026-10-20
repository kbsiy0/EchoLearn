import { useNavigate } from 'react-router-dom';

type Props = {
  progress: number;
  error?: string | null;
  title?: string | null;
};

export function ProcessingPlaceholder({ progress, error, title }: Props) {
  const navigate = useNavigate();

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
        <h3 className="text-red-400 text-lg">處理失敗</h3>
        <p className="text-gray-400 text-sm">{error}</p>
        <button
          onClick={() => navigate('/')}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
        >
          回首頁
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
      {title && <p className="text-gray-400 text-sm truncate">{title}</p>}
      <div className="w-full max-w-sm">
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-[width] duration-200"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <p className="text-gray-300 text-sm">處理字幕中 ({progress}%)</p>
    </div>
  );
}
