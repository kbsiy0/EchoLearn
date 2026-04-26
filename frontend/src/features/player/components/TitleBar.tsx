interface TitleBarProps {
  title: string | null;
}

export function TitleBar({ title }: TitleBarProps) {
  if (!title) return null;
  return (
    <span className="text-gray-400 text-sm truncate ml-4 shrink-0 py-2 px-6 bg-gray-800 border-b border-gray-700 block">
      {title}
    </span>
  );
}
