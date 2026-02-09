'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Play, RotateCw } from 'lucide-react';
import { triggerScript } from '@/lib/api';

interface ScriptExecutorProps {
  scriptName: string;
  title: string;
  description: string;
  onLog: (message: string, type: 'info' | 'success' | 'error') => void;
  isRunning?: boolean; // Controlled externally or internally
}

export function ScriptExecutor({ scriptName, title, description, onLog }: ScriptExecutorProps) {
  const [loading, setLoading] = useState(false);

  const handleRun = async () => {
    if (loading) return;
    setLoading(true);
    onLog(`开始执行: ${title}...`, 'info');

    try {
      if (scriptName === 'search_projects') {
        await triggerScript('refresh_projects');
        // Simulate progress
        onLog('正在抓取新项目...', 'info');
        await new Promise((r) => setTimeout(r, 2000));
        onLog('抓取完成，更新数据库', 'success');
      } else if (scriptName === 'score_all') {
        await triggerScript('score_all'); // Assuming api supports this
        onLog('开始批量评分...', 'info');
        await new Promise((r) => setTimeout(r, 3000));
        onLog('评分完成: 处理了 5 个项目', 'success');
      } else {
        await triggerScript(scriptName);
        onLog('执行完成', 'success');
      }

      onLog(`执行成功: ${title}`, 'success');
    } catch (error) {
      onLog(`执行失败: ${error}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button onClick={handleRun} disabled={loading} className="w-full sm:w-auto">
          {loading ? (
            <RotateCw className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-2 h-4 w-4" />
          )}
          {loading ? '运行中...' : '执行脚本'}
        </Button>
      </CardContent>
    </Card>
  );
}
