'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { BarChart2, Save, Loader2, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { getScoringRules, updateScoringRule } from '@/lib/api';
import { ScoringRule } from '@/lib/types';
import { ApiErrorDisplay } from '@/components/ui/ErrorBoundary';

export default function ScoringPage() {
  const queryClient = useQueryClient();
  const [localWeights, setLocalWeights] = useState<Record<number, number>>({});

  const {
    data: rules = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['scoringRules'],
    queryFn: getScoringRules,
  });

  const updateMutation = useMutation({
    mutationFn: (data: { id: number; weight: number }) =>
      updateScoringRule(data.id, { weight: data.weight }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scoringRules'] });
    },
    onError: (err) => {
      alert('Failed to update: ' + err);
    },
  });

  const handleWeightChange = (id: number, value: string) => {
    const numVal = parseFloat(value);
    setLocalWeights((prev) => ({ ...prev, [id]: numVal }));
  };

  const handleSave = async () => {
    // Save all changed weights
    const promises = Object.entries(localWeights).map(([idStr, weight]) => {
      return updateMutation.mutateAsync({ id: parseInt(idStr), weight });
    });

    try {
      await Promise.all(promises);
      setLocalWeights({});
      alert('配置已保存');
    } catch (e) {
      console.error(e);
    }
  };

  const getWeight = (rule: ScoringRule) => {
    return localWeights[rule.id] !== undefined ? localWeights[rule.id] : rule.weight;
  };

  const totalWeight = rules.reduce((acc, rule) => acc + getWeight(rule), 0);
  const totalPercentage = Math.round(totalWeight * 100);

  if (isLoading) {
    return (
      <div className="flex justify-center p-20">
        <Loader2 className="animate-spin h-8 w-8" />
      </div>
    );
  }

  if (isError) {
    return (
      <ApiErrorDisplay
        message={error instanceof Error ? error.message : 'Failed to load rules'}
        onRetry={refetch}
      />
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">评分系统配置</h1>
        <p className="text-gray-500">调整项目评分算法的权重与参数</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Weights */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <div className="flex justify-between items-center">
                <div>
                  <CardTitle>核心权重 (Core Weights)</CardTitle>
                  <CardDescription>各评估维度在最终评分中的占比 (从后端加载)</CardDescription>
                </div>
                <Badge variant={Math.abs(totalPercentage - 100) < 5 ? 'default' : 'destructive'}>
                  总计: {totalPercentage}%
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {rules.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <AlertCircle className="mx-auto h-8 w-8 mb-2" />
                  <p>未找到评分规则配置</p>
                </div>
              ) : (
                rules.map((rule) => (
                  <div key={rule.id} className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <div className="flex flex-col">
                        <span className="font-medium capitalize">
                          {rule.name.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs text-gray-400">{rule.description}</span>
                      </div>
                      <span className="text-gray-500">{Math.round(getWeight(rule) * 100)}%</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={getWeight(rule)}
                      onChange={(e) => handleWeightChange(rule.id, e.target.value)}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                    />
                  </div>
                ))
              )}

              <div className="pt-4 border-t">
                <Button
                  className="w-full"
                  onClick={handleSave}
                  disabled={Object.keys(localWeights).length === 0 || updateMutation.isPending}
                >
                  {updateMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4 mr-2" />
                  )}
                  保存权重配置
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Customer Scoring Section Placeholder */}
          <Card className="opacity-70 pointer-events-none">
            <CardHeader>
              <CardTitle>高级参数 (Coming Soon)</CardTitle>
              <CardDescription>更多细粒度的评分参数配置将在后续版本开放</CardDescription>
            </CardHeader>
          </Card>
        </div>

        {/* Right Column: Preview */}
        <div className="space-y-6">
          <Card className="bg-slate-50 border-slate-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BarChart2 className="w-5 h-5" />
                效果预览
              </CardTitle>
              <CardDescription>模拟评分结果 (基于当前权重)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Mock preview logic - roughly estimating based on rules presence */}
              <div className="p-4 bg-white rounded-lg border shadow-sm">
                <div className="text-xs text-gray-500 mb-1">标准项目 (Standard)</div>
                <div className="flex justify-between items-end">
                  <div className="text-2xl font-bold text-blue-600">
                    {/* Calculate pseudo score */}
                    {(totalWeight * 8.5).toFixed(1)}
                  </div>
                  <div className="text-xs text-green-600 font-medium">Good</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
