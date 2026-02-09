'use client';

import { useState } from 'react';
import { Play, RotateCw, Terminal, Activity } from 'lucide-react';
import { triggerScript } from '@/lib/api';

interface ScriptLog {
  id: number;
  time: string;
  message: string;
  type: 'info' | 'success' | 'error';
}

export default function ScriptsPage() {
  const [runningScript, setRunningScript] = useState<string | null>(null);
  const [logs, setLogs] = useState<ScriptLog[]>([]);

  const addLog = (message: string, type: 'info' | 'success' | 'error' = 'info') => {
    setLogs((prev) => [
      {
        id: Date.now(),
        time: new Date().toLocaleTimeString(),
        message,
        type,
      },
      ...prev,
    ]);
  };

  const handleRunScript = async (scriptName: string, label: string) => {
    if (runningScript) return;

    setRunningScript(scriptName);
    addLog(`开始执行: ${label}...`, 'info');

    try {
      if (scriptName === 'search_projects') {
        addLog('正在调用 API 抓取新项目...', 'info');
        const res = await triggerScript('refresh_projects');
        addLog(`抓取成功: 获取了 ${res.data?.total || 0} 个项目`, 'success');
      } else if (scriptName === 'score_all') {
        addLog('正在启动批量评分任务...', 'info');
        await triggerScript('score_all');
        addLog('评分任务已触发 (模拟批处理)', 'success');
      } else {
        await new Promise((r) => setTimeout(r, 1000));
        addLog('未知脚本', 'error');
      }

      addLog(`任务完成: ${label}`, 'success');
    } catch (error: any) {
      addLog(`执行失败: ${error.message || '未知错误'}`, 'error');
    } finally {
      setRunningScript(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">脚本控制台</h1>
        <p className="text-gray-500">手动触发后台自动化任务</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Script Cards */}
        <div className="space-y-4">
          <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-blue-50 text-blue-600 rounded-lg">
                <RotateCw size={24} />
              </div>
              <div>
                <h3 className="font-semibold text-gray-900">刷新项目库</h3>
                <p className="text-sm text-gray-500">从 Freelancer.com 抓取最新项目</p>
              </div>
            </div>
            <button
              onClick={() => handleRunScript('search_projects', '刷新项目库')}
              disabled={!!runningScript}
              className={`px-4 py-2 rounded-lg flex items-center gap-2 font-medium transition-colors text-sm ${
                runningScript === 'search_projects'
                  ? 'bg-blue-100 text-blue-700 cursor-wait'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
              }`}
            >
              {runningScript === 'search_projects' ? (
                <RotateCw className="animate-spin" size={16} />
              ) : (
                <Play size={16} />
              )}
              {runningScript === 'search_projects' ? '运行中' : '执行'}
            </button>
          </div>

          <div className="bg-white p-6 rounded-xl border border-gray-100 shadow-sm flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 bg-purple-50 text-purple-600 rounded-lg">
                <Activity size={24} />
              </div>
              <div>
                <h3 className="font-semibold text-gray-900">批量AI评分</h3>
                <p className="text-sm text-gray-500">对所有未评分的开放项目进行评分</p>
              </div>
            </div>
            <button
              onClick={() => handleRunScript('score_all', '批量AI评分')}
              disabled={!!runningScript}
              className={`px-4 py-2 rounded-lg flex items-center gap-2 font-medium transition-colors text-sm ${
                runningScript === 'score_all'
                  ? 'bg-purple-100 text-purple-700 cursor-wait'
                  : 'bg-purple-600 text-white hover:bg-purple-700'
              }`}
            >
              {runningScript === 'score_all' ? (
                <RotateCw className="animate-spin" size={16} />
              ) : (
                <Play size={16} />
              )}
              {runningScript === 'score_all' ? '运行中' : '执行'}
            </button>
          </div>
        </div>

        {/* Console / Logs */}
        <div className="bg-gray-900 rounded-xl shadow-lg p-4 font-mono text-sm h-[400px] flex flex-col">
          <div className="flex items-center gap-2 text-gray-400 mb-4 pb-2 border-b border-gray-800">
            <Terminal size={16} />
            <span>执行日志</span>
          </div>
          <div className="flex-1 overflow-auto space-y-2">
            {logs.length === 0 && <span className="text-gray-600 italic">暂无日志...</span>}
            {logs.map((log) => (
              <div key={log.id} className="flex gap-3">
                <span className="text-gray-500 select-none">[{log.time}]</span>
                <span
                  className={
                    log.type === 'error'
                      ? 'text-red-400'
                      : log.type === 'success'
                        ? 'text-green-400'
                        : 'text-gray-300'
                  }
                >
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
