'use client';

import { useState, useEffect } from 'react';
import { Save, Server, Database, Key, Globe } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { checkHealth } from '@/lib/api';

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('');
  const [apiUrl, setApiUrl] = useState('http://localhost:8000/api/v1');
  const [status, setStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');
  const [serviceInfo, setServiceInfo] = useState<any>(null);

  useEffect(() => {
    // Load from local storage
    const storedKey = localStorage.getItem('api_key');
    const storedUrl = localStorage.getItem('api_url');
    if (storedKey) setApiKey(storedKey);
    if (storedUrl) setApiUrl(storedUrl);

    checkConnection();
  }, []);

  const checkConnection = async () => {
    setStatus('checking');
    const data = await checkHealth();
    if (data && data.status === 'healthy') {
      setStatus('connected');
      setServiceInfo(data);
    } else {
      setStatus('disconnected');
    }
  };

  const handleSave = () => {
    localStorage.setItem('api_key', apiKey);
    localStorage.setItem('api_url', apiUrl);
    checkConnection();
    // Simple alert for now since we don't have a toast component confirmed
    alert('设置已保存');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">系统设置</h1>
        <p className="text-gray-500">配置 API 连接和其他选项</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Connection Status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              系统状态
            </CardTitle>
            <CardDescription>后端服务连接状态监控</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border">
              <div className="flex items-center gap-3">
                <div
                  className={`h-3 w-3 rounded-full ${
                    status === 'connected'
                      ? 'bg-green-500'
                      : status === 'checking'
                        ? 'bg-yellow-500'
                        : 'bg-red-500'
                  }`}
                />
                <span className="font-medium">API 服务</span>
              </div>
              <Badge variant={status === 'connected' ? 'default' : 'destructive'}>
                {status === 'connected' ? '已连接' : status === 'checking' ? '检测中...' : '未连接'}
              </Badge>
            </div>

            {serviceInfo && (
              <div className="text-sm text-gray-500 space-y-1">
                <p>版本: {serviceInfo.version}</p>
                <p>服务名: {serviceInfo.service}</p>
              </div>
            )}

            <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border">
              <div className="flex items-center gap-3">
                <Database className="h-4 w-4 text-gray-500" />
                <span className="font-medium">数据库</span>
              </div>
              <Badge variant={status === 'connected' ? 'outline' : 'outline'} className="bg-white">
                {status === 'connected' ? '正常' : '未知'}
              </Badge>
            </div>

            <Button variant="outline" size="sm" onClick={checkConnection} className="w-full">
              刷新状态
            </Button>
          </CardContent>
        </Card>

        {/* API Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-5 w-5" />
              接口配置
            </CardTitle>
            <CardDescription>配置后端 API 地址和访问密钥</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium flex items-center gap-2">API Base URL</label>
              <Input
                placeholder="http://localhost:8000/api/v1"
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium flex items-center gap-2">
                <Key className="h-4 w-4" />
                API Key
              </label>
              <Input
                type="password"
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>

            <Button onClick={handleSave} className="w-full gap-2">
              <Save className="h-4 w-4" />
              保存配置
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
