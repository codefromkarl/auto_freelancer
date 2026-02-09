'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getProject, scoreProject, createBid } from '@/lib/api';
import { useParams } from 'next/navigation';
import {
  ArrowLeft,
  CheckCircle,
  Play,
  Send,
  AlertTriangle,
  Clock,
  MapPin,
  Code2,
} from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { LoadingState } from '@/components/ui/LoadingState';
// Separator replaced with div border-b

export default function ProjectDetailPage() {
  const { id } = useParams();
  const queryClient = useQueryClient();

  // Safe parsing of ID
  const rawId = Array.isArray(id) ? id[0] : id;
  const projectId = rawId ? parseInt(rawId) : 0;

  const [isBidding, setIsBidding] = useState(false);
  const [bidAmount, setBidAmount] = useState<number>(0);
  const [bidPeriod, setBidPeriod] = useState<number>(7);

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
    enabled: !!projectId,
  });

  const scoreMutation = useMutation({
    mutationFn: scoreProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      alert('评分已触发'); // Could use toast here later
    },
    onError: (err) => {
      alert('评分失败: ' + err);
    },
  });

  const bidMutation = useMutation({
    mutationFn: (data: { amount: number; period: number }) =>
      createBid(projectId, {
        amount: data.amount,
        period: data.period,
        description: project?.ai_proposal_draft || 'Generated proposal',
        bidder_id: 12345,
      }),
    onSuccess: () => {
      setIsBidding(false);
      alert('投标已提交');
    },
    onError: (err) => {
      alert('投标失败: ' + err);
    },
  });

  if (isLoading)
    return (
      <div className="p-12">
        <LoadingState message="加载项目详情..." />
      </div>
    );
  if (!project) return <div className="p-12 text-center text-red-500">未找到项目</div>;

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-20 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <Button variant="ghost" size="sm" asChild className="pl-0 hover:pl-2 transition-all">
        <Link href="/projects">
          <ArrowLeft size={16} className="mr-2" /> 返回列表
        </Link>
      </Button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <div className="flex justify-between items-start gap-4">
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <Badge variant={project.status === 'active' ? 'default' : 'secondary'}>
                      {project.status === 'active' ? '开放' : project.status}
                    </Badge>
                    <span className="text-sm text-muted-foreground">ID: {project.id}</span>
                  </div>
                  <CardTitle className="text-2xl font-bold leading-tight">
                    {project.title}
                  </CardTitle>
                  <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground pt-1">
                    <span className="flex items-center gap-1 font-medium text-foreground">
                      {project.currency_code} {project.budget_minimum} - {project.budget_maximum}
                    </span>
                    <span>•</span>
                    <span className="flex items-center gap-1">
                      <Clock size={14} />
                      {new Date(project.submitdate || '').toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1 shrink-0">
                  <div
                    className={`text-4xl font-bold tracking-tighter ${
                      (project.ai_score || 0) > 7 ? 'text-green-600' : 'text-muted-foreground'
                    }`}
                  >
                    {project.ai_score ? project.ai_score.toFixed(1) : 'N/A'}
                  </div>
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    AI Score
                  </span>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <Tabs defaultValue="description" className="w-full">
                <TabsList className="grid w-full grid-cols-3 mb-6">
                  <TabsTrigger value="description">项目描述</TabsTrigger>
                  <TabsTrigger value="analysis">AI 分析</TabsTrigger>
                  <TabsTrigger value="proposal">提案草稿</TabsTrigger>
                </TabsList>

                <TabsContent value="description" className="space-y-4">
                  <div className="prose prose-sm max-w-none text-foreground/80 whitespace-pre-wrap leading-relaxed">
                    {project.description}
                  </div>
                </TabsContent>

                <TabsContent value="analysis" className="space-y-4">
                  {project.ai_reason ? (
                    <div className="bg-blue-50/50 dark:bg-blue-950/10 p-6 rounded-lg border border-blue-100 dark:border-blue-900">
                      <h3 className="text-base font-semibold text-blue-900 dark:text-blue-200 mb-3 flex items-center gap-2">
                        <CheckCircle size={18} /> 核心分析
                      </h3>
                      <div className="text-blue-800 dark:text-blue-300 text-sm whitespace-pre-wrap leading-relaxed">
                        {project.ai_reason}
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">
                      <AlertTriangle className="mx-auto h-8 w-8 mb-2 opacity-50" />
                      暂无 AI 分析报告，请尝试点击"重新评分"
                    </div>
                  )}
                </TabsContent>

                <TabsContent value="proposal" className="space-y-4">
                  {project.ai_proposal_draft ? (
                    <div className="relative">
                      <div className="absolute top-2 right-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs px-2"
                          onClick={() =>
                            navigator.clipboard.writeText(project.ai_proposal_draft || '')
                          }
                        >
                          复制
                        </Button>
                      </div>
                      <pre className="whitespace-pre-wrap text-sm font-mono bg-muted/50 p-6 rounded-lg border border-border overflow-auto max-h-[500px]">
                        {project.ai_proposal_draft}
                      </pre>
                    </div>
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">暂无提案草稿</div>
                  )}
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar Actions */}
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">操作面板</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => scoreMutation.mutate(projectId)}
                disabled={scoreMutation.isPending}
              >
                {scoreMutation.isPending ? (
                  <Clock className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                重新执行 AI 评分
              </Button>

              {!isBidding ? (
                <Button
                  className="w-full justify-start bg-blue-600 hover:bg-blue-700 text-white"
                  onClick={() => {
                    setBidAmount(project.suggested_bid || project.budget_minimum || 0);
                    setIsBidding(true);
                  }}
                >
                  <Send className="mr-2 h-4 w-4" /> 准备投标
                </Button>
              ) : (
                <div className="bg-muted/50 p-4 rounded-lg border space-y-4 animate-in fade-in zoom-in-95 duration-200">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">
                      投标金额 ({project.currency_code})
                    </label>
                    <Input
                      type="number"
                      value={bidAmount}
                      onChange={(e) => setBidAmount(parseFloat(e.target.value))}
                      className="bg-white h-8"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">
                      交付周期 (天)
                    </label>
                    <Input
                      type="number"
                      value={bidPeriod}
                      onChange={(e) => setBidPeriod(parseInt(e.target.value))}
                      className="bg-white h-8"
                    />
                  </div>
                  <div className="flex gap-2 pt-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="flex-1 h-8"
                      onClick={() => setIsBidding(false)}
                    >
                      取消
                    </Button>
                    <Button
                      size="sm"
                      className="flex-1 h-8 bg-blue-600 hover:bg-blue-700 text-white"
                      onClick={() => bidMutation.mutate({ amount: bidAmount, period: bidPeriod })}
                      disabled={bidMutation.isPending}
                    >
                      {bidMutation.isPending ? '提交中...' : '确认提交'}
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">项目信息</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Clock size={14} /> 截止日期
                </span>
                <span className="font-medium">
                  {project.deadline ? new Date(project.deadline).toLocaleDateString() : 'N/A'}
                </span>
              </div>
              <div className="border-b border-border/50" />
              <div className="flex items-start justify-between">
                <span className="text-muted-foreground flex items-center gap-2 mt-0.5">
                  <Code2 size={14} /> 技能要求
                </span>
                <span className="font-medium text-right w-2/3">{project.skills || 'N/A'}</span>
              </div>
              <div className="border-b border-border/50" />
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground flex items-center gap-2">
                  <MapPin size={14} /> 雇主国家
                </span>
                <span className="font-medium">{project.country || '未知'}</span>
              </div>
            </CardContent>
          </Card>

          {project.owner_info && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">雇主情报</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs text-muted-foreground overflow-auto max-h-40 bg-muted/30 p-2 rounded border font-mono">
                  {JSON.stringify(project.owner_info, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
