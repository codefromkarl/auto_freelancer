import { RotateCw } from 'lucide-react';

export function LoadingState({ message = 'Loading...' }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 w-full text-gray-500 animate-in fade-in duration-300">
      <RotateCw className="w-8 h-8 animate-spin mb-4 text-primary" />
      <p className="text-sm font-medium">{message}</p>
    </div>
  );
}
