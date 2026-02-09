'use client';

import { useState, useEffect, Component, ErrorInfo, ReactNode } from 'react';
import { RefreshCw, WifiOff, ServerCrash, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  public render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <ErrorDisplay
            error={this.state.error}
            onRetry={() => this.setState({ hasError: false, error: null, errorInfo: null })}
          />
        )
      );
    }

    return this.props.children;
  }
}

// Error display component
function ErrorDisplay({ error, onRetry }: { error: Error | null; onRetry: () => void }) {
  const [errorMessage, setErrorMessage] = useState<string>('加载失败，请稍后重试');
  const [isNetworkError, setIsNetworkError] = useState(false);

  useEffect(() => {
    if (error) {
      // Check if it's a network error
      if (error.message?.includes('network') || error.message?.includes('fetch')) {
        setIsNetworkError(true);
        setErrorMessage('无法连接到服务器，请检查网络连接或后端服务是否运行');
      } else if (error.message) {
        setErrorMessage(error.message);
      }
    }
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center h-64 w-full text-gray-500 animate-in fade-in duration-300">
      {isNetworkError ? (
        <WifiOff className="w-12 h-12 text-orange-500 mb-4" />
      ) : (
        <ServerCrash className="w-12 h-12 text-red-500 mb-4" />
      )}
      <div className="text-center space-y-2">
        <p className="text-lg font-medium text-gray-700">{errorMessage}</p>
        <p className="text-sm text-gray-400">数据加载失败，请点击下方按钮重试</p>
      </div>
      <Button variant="outline" size="sm" onClick={onRetry} className="mt-4 gap-2">
        <RefreshCw className="w-4 h-4" />
        重新加载
      </Button>
    </div>
  );
}

// API Error display component
export function ApiErrorDisplay({
  message,
  onRetry,
  isLoading,
}: {
  message?: string;
  onRetry?: () => void;
  isLoading?: boolean;
}) {
  if (!message) return null;

  return (
    <div className="flex flex-col items-center justify-center h-48 w-full text-gray-500 bg-gray-50 rounded-lg border border-dashed border-gray-200 animate-in fade-in duration-300">
      <AlertTriangle className="w-8 h-8 text-orange-500 mb-3" />
      <p className="text-sm font-medium text-gray-600 px-4 text-center">
        {message || '数据加载失败'}
      </p>
      {onRetry && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onRetry}
          disabled={isLoading}
          className="mt-3 gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
          {isLoading ? '加载中...' : '重试'}
        </Button>
      )}
    </div>
  );
}

// Inline error alert component
export function ErrorAlert({ message, className }: { message: string; className?: string }) {
  return (
    <div
      className={`flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 ${className || ''}`}
    >
      <AlertTriangle className="w-4 h-4 flex-shrink-0" />
      <span>{message}</span>
    </div>
  );
}
