'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getProposals,
  getProposalStats,
  getCompetitorAnalysis,
  getProposalTemplates,
  createProposalTemplate,
  deleteProposalTemplate,
  updateProposalTemplate,
} from '@/lib/api';
import Link from 'next/link';
import {
  FileText,
  Users,
  TrendingUp,
  Plus,
  Trash2,
  Edit,
  CheckCircle,
  XCircle,
  Clock,
  ArrowUpRight,
  Copy,
  Sparkles,
  Loader2,
  RefreshCw,
  AlertCircle,
  Save,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { ApiErrorDisplay } from '@/components/ui/ErrorBoundary';
import { Proposal, CompetitorAnalysis, ProposalTemplate } from '@/lib/types';

// Fallback data when API is unavailable
const FALLBACK_PROPOSALS: Proposal[] = [
  {
    id: 1,
    project_id: 101,
    project_title: 'E-commerce Website Development',
    project_budget: '$500 - $1000',
    amount: 750,
    period: 14,
    description: 'Full stack e-commerce solution with payment integration',
    status: 'pending',
    submitdate: '2026-01-10',
    ai_score: 8.5,
    competitor_count: 12,
    win_probability: 0.35,
  },
  {
    id: 2,
    project_id: 102,
    project_title: 'Mobile App for Delivery Service',
    project_budget: '$1000 - $2000',
    amount: 1500,
    period: 30,
    description: 'React Native delivery app with GPS tracking',
    status: 'accepted',
    submitdate: '2026-01-08',
    ai_score: 9.2,
    competitor_count: 8,
    win_probability: 0.65,
  },
  {
    id: 3,
    project_id: 103,
    project_title: 'Data Analysis Dashboard',
    project_budget: '$300 - $500',
    amount: 400,
    period: 7,
    description: 'Python data visualization dashboard',
    status: 'rejected',
    submitdate: '2026-01-05',
    ai_score: 5.8,
    competitor_count: 25,
    win_probability: 0.15,
  },
];

const FALLBACK_TEMPLATES: ProposalTemplate[] = [
  {
    id: 1,
    name: 'Web Development Template',
    category: 'proposal',
    content: 'I am an experienced full-stack developer with 5+ years of experience in React, Node.js, and modern web technologies.',
    variables: ['React', 'Node.js', 'Python'],
    is_active: true,
    created_at: '2026-01-01',
  },
  {
    id: 2,
    name: 'Mobile App Template',
    category: 'proposal',
    content: 'I specialize in mobile application development with React Native and Flutter.',
    variables: ['React Native', 'Flutter'],
    is_active: false,
    created_at: '2026-01-05',
  },
];

const FALLBACK_STATS = {
  total: 45,
  accepted: 12,
  rejected: 18,
  pending: 15,
  success_rate: 40,
  avg_amount: 850,
};

const FALLBACK_COMPETITORS: CompetitorAnalysis[] = [
  {
    bidder_id: 1,
    bidder_name: 'TopDev_Pro',
    amount: 800,
    period: 14,
    rating: 4.9,
    bid_count: 156,
    success_rate: 78,
  },
  {
    bidder_id: 2,
    bidder_name: 'WebMaster_Expert',
    amount: 700,
    period: 10,
    rating: 4.7,
    bid_count: 89,
    success_rate: 65,
  },
];

export default function ProposalsPage() {
  const [activeTab, setActiveTab] = useState('list');
  const [showTemplateDialog, setShowTemplateDialog] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<ProposalTemplate | null>(null);
  const [newTemplate, setNewTemplate] = useState({ name: '', content: '', skills: '' });
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [showCompetitors, setShowCompetitors] = useState(false);
  const [competitorProjectId, setCompetitorProjectId] = useState<string>('');
  const [pageError, setPageError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  // Fetch proposals with error handling
  const {
    data: proposals = FALLBACK_PROPOSALS,
    isLoading: proposalsLoading,
    isError: proposalsError,
    error: proposalsErrorObj,
    refetch: refetchProposals,
  } = useQuery({
    queryKey: ['proposals'],
    queryFn: () => getProposals(),
    placeholderData: FALLBACK_PROPOSALS,
    retry: 2,
    refetchOnMount: true,
  });

  // Fetch proposal stats
  const {
    data: stats = FALLBACK_STATS,
    isLoading: statsLoading,
    isError: statsError,
    error: statsErrorObj,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ['proposalStats'],
    queryFn: () => getProposalStats(),
    placeholderData: FALLBACK_STATS,
    retry: 2,
    refetchOnMount: true,
  });

  // Fetch proposal templates
  const {
    data: templates = FALLBACK_TEMPLATES,
    isLoading: templatesLoading,
    isError: templatesError,
    error: templatesErrorObj,
    refetch: refetchTemplates,
  } = useQuery({
    queryKey: ['proposalTemplates'],
    queryFn: () => getProposalTemplates(),
    placeholderData: FALLBACK_TEMPLATES,
    retry: 2,
    refetchOnMount: true,
  });

  // Fetch competitors for specific project
  const {
    data: competitors = FALLBACK_COMPETITORS,
    isLoading: competitorsLoading,
    isError: competitorsError,
    refetch: refetchCompetitors,
  } = useQuery({
    queryKey: ['competitors', competitorProjectId || selectedProposal?.project_id],
    queryFn: () => {
      const projectId = competitorProjectId || selectedProposal?.project_id;
      if (!projectId) return FALLBACK_COMPETITORS;
      return getCompetitorAnalysis(Number(projectId));
    },
    enabled: !!(competitorProjectId || selectedProposal?.project_id),
    placeholderData: FALLBACK_COMPETITORS,
    retry: 2,
  });

  // Create template mutation
  const createTemplateMutation = useMutation({
    mutationFn: async (data: { name: string; content: string; skills: string[]; is_active: boolean }) => {
      return createProposalTemplate({
        name: data.name,
        content: data.content,
        category: 'proposal',
        variables: data.skills,
        is_active: data.is_active,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposalTemplates'] });
      setShowTemplateDialog(false);
      setNewTemplate({ name: '', content: '', skills: '' });
    },
    onError: (error: Error) => {
      console.error('Failed to create template:', error);
    },
  });

  // Update template mutation
  const updateTemplateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<ProposalTemplate> }) => {
      return updateProposalTemplate(id, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposalTemplates'] });
      setEditingTemplate(null);
      setNewTemplate({ name: '', content: '', skills: '' });
      setShowTemplateDialog(false);
    },
    onError: (error: Error) => {
      console.error('Failed to update template:', error);
    },
  });

  // Delete template mutation
  const deleteTemplateMutation = useMutation({
    mutationFn: async (id: number) => {
      return deleteProposalTemplate(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposalTemplates'] });
    },
    onError: (error: Error) => {
      console.error('Failed to delete template:', error);
    },
  });

  const handleRefresh = async () => {
    setPageError(null);
    try {
      await Promise.all([refetchProposals(), refetchStats(), refetchTemplates()]);
    } catch {
      setPageError('刷新数据失败，请检查网络连接');
    }
  };

  const handleAnalyzeCompetitors = () => {
    if (competitorProjectId) {
      refetchCompetitors();
    }
  };

  const handleViewCompetitors = (proposal: Proposal) => {
    setSelectedProposal(proposal);
    setShowCompetitors(true);
  };

  const handleEditTemplate = (template: ProposalTemplate) => {
    setEditingTemplate(template);
    setNewTemplate({
      name: template.name,
      content: template.content,
      skills: template.variables?.join(', ') || '',
    });
    setShowTemplateDialog(true);
  };

  const handleSaveTemplate = () => {
    const templateData = {
      name: newTemplate.name,
      content: newTemplate.content,
      skills: newTemplate.skills.split(',').map((s) => s.trim()).filter(Boolean),
      is_active: false,
    };

    if (editingTemplate) {
      updateTemplateMutation.mutate({ id: editingTemplate.id, data: templateData });
    } else {
      createTemplateMutation.mutate(templateData);
    }
  };

  const handleCloseTemplateDialog = () => {
    setShowTemplateDialog(false);
    setEditingTemplate(null);
    setNewTemplate({ name: '', content: '', skills: '' });
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'accepted':
        return (
          <Badge className="bg-green-500">
            <CheckCircle className="mr-1 h-3 w-3" />
            已中标
          </Badge>
        );
      case 'rejected':
        return (
          <Badge variant="destructive">
            <XCircle className="mr-1 h-3 w-3" />
            已拒绝
          </Badge>
        );
      case 'pending':
        return (
          <Badge variant="outline">
            <Clock className="mr-1 h-3 w-3" />
            待定
          </Badge>
        );
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">标书管理</h1>
          <p className="text-muted-foreground mt-1">管理投标历史、分析竞品、查看成功率</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={proposalsLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${proposalsLoading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          <Button asChild>
            <Link href="/projects">
              <Plus className="mr-2 h-4 w-4" />
              新建投标
            </Link>
          </Button>
        </div>
      </div>

      {/* Error display */}
      {pageError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md flex items-center gap-2 text-red-700">
          <AlertCircle className="w-4 h-4" />
          {pageError}
        </div>
      )}

      {/* Stats Cards */}
      {statsError ? (
        <ApiErrorDisplay
          message={statsErrorObj instanceof Error ? statsErrorObj.message : '加载统计数据失败'}
          onRetry={handleRefresh}
          isLoading={statsLoading}
        />
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">总投标数</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <>
                <div className="text-2xl font-bold">{stats?.total || 0}</div>
                <p className="text-xs text-muted-foreground">累计投标</p>
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">成功率</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <>
                <div className="text-2xl font-bold">{stats?.success_rate || 0}%</div>
                <Progress value={stats?.success_rate || 0} className="mt-2" />
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">已中标</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <>
                <div className="text-2xl font-bold text-green-600">{stats?.accepted || 0}</div>
                <p className="text-xs text-muted-foreground">中标项目</p>
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">平均金额</CardTitle>
            <Sparkles className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {statsLoading ? (
              <Loader2 className="h-6 w-6 animate-spin" />
            ) : (
              <>
                <div className="text-2xl font-bold">${stats?.avg_amount || 0}</div>
                <p className="text-xs text-muted-foreground">平均中标金额</p>
              </>
            )}
          </CardContent>
        </Card>
      </div>
      )}

      {/* Main Content */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="list">投标历史</TabsTrigger>
          <TabsTrigger value="templates">提案模板</TabsTrigger>
          <TabsTrigger value="analytics">竞品分析</TabsTrigger>
        </TabsList>

        {/* Proposal List Tab */}
        <TabsContent value="list" className="space-y-4">
          <Card>
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>项目</TableHead>
                  <TableHead>投标金额</TableHead>
                  <TableHead>AI评分</TableHead>
                  <TableHead>中标概率</TableHead>
                  <TableHead>竞品数</TableHead>
                  <TableHead>提交时间</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {proposalsLoading ? (
                  <TableRow>
                    <TableCell colSpan={8} className="h-24 text-center">
                      <div className="flex justify-center items-center gap-2">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        加载中...
                      </div>
                    </TableCell>
                  </TableRow>
                ) : proposals.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="h-24 text-center text-muted-foreground">
                      暂无投标记录
                    </TableCell>
                  </TableRow>
                ) : (
                  proposals.map((proposal) => (
                    <TableRow key={proposal.id}>
                      <TableCell>
                        <div className="font-medium">{proposal.project_title}</div>
                        <div className="text-xs text-muted-foreground line-clamp-1">
                          {proposal.description}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-mono">${proposal.amount}</div>
                        <div className="text-xs text-muted-foreground">{proposal.period}天</div>
                      </TableCell>
                      <TableCell>
                        <div
                          className={`font-semibold ${
                            (proposal.ai_score || 0) > 7
                              ? 'text-green-600'
                              : (proposal.ai_score || 0) > 4
                                ? 'text-orange-600'
                                : ''
                          }`}
                        >
                          {proposal.ai_score?.toFixed(1) || '-'}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress
                            value={(proposal.win_probability || 0) * 100}
                            className="h-2 w-16"
                          />
                          <span className="text-xs">
                            {Math.round((proposal.win_probability || 0) * 100)}%
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleViewCompetitors(proposal)}
                        >
                          <Users className="mr-1 h-3 w-3" />
                          {proposal.competitor_count || 0}
                        </Button>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {new Date(proposal.submitdate || '').toLocaleDateString()}
                      </TableCell>
                      <TableCell>{getStatusBadge(proposal.status)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" asChild>
                          <Link href={`/projects/${proposal.project_id}`}>
                            <ArrowUpRight className="h-4 w-4" />
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        {/* Templates Tab */}
        <TabsContent value="templates" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={handleCloseTemplateDialog}>
              <Plus className="mr-2 h-4 w-4" />
              添加模板
            </Button>
          </div>
          {templatesLoading ? (
            <div className="flex justify-center p-10">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {templates.length === 0 ? (
                <div className="col-span-2 text-center py-10 text-gray-500">暂无模板</div>
              ) : (
                templates.map((template) => (
                  <Card key={template.id}>
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <div>
                          <CardTitle className="text-lg">{template.name}</CardTitle>
                          <CardDescription>
                            创建于 {new Date(template.created_at).toLocaleDateString()}
                          </CardDescription>
                        </div>
                            <div className="flex gap-2">
                              {template.is_active && <Badge variant="secondary">默认</Badge>}
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleEditTemplate(template)}
                              >
                                <Edit className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => deleteTemplateMutation.mutate(template.id)}
                                disabled={template.is_active}
                              >
                                <Trash2 className="h-4 w-4 text-red-500" />
                              </Button>
                            </div>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-3">
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {template.content}
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {template.variables?.map((skill) => (
                            <Badge key={skill} variant="outline" className="text-xs">
                              {skill}
                            </Badge>
                          ))}
                        </div>
                        <div className="flex gap-2 pt-2">
                          <Button variant="outline" size="sm">
                            <Copy className="mr-1 h-3 w-3" />
                            复制
                          </Button>
                          <Button variant="outline" size="sm">
                            <ArrowUpRight className="mr-1 h-3 w-3" />
                            使用
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))
              )}
            </div>
          )}
        </TabsContent>

        {/* Competitor Analysis Tab */}
        <TabsContent value="analytics" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>竞品分析</CardTitle>
              <CardDescription>查看特定项目的竞争对手信息</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex gap-4 items-center">
                  <Input
                    placeholder="输入项目ID查看竞品"
                    className="max-w-xs"
                    value={competitorProjectId}
                    onChange={(e) => setCompetitorProjectId(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAnalyzeCompetitors()}
                  />
                  <Button
                    onClick={handleAnalyzeCompetitors}
                    disabled={!competitorProjectId || competitorsLoading}
                  >
                    {competitorsLoading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        分析中...
                      </>
                    ) : (
                      <>
                        <Users className="mr-2 h-4 w-4" />
                        分析
                      </>
                    )}
                  </Button>
                </div>
                {competitorsError ? (
                  <div className="p-4 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" />
                    加载竞品数据失败，请检查项目ID或网络连接
                  </div>
                ) : (
                  <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead>竞标者</TableHead>
                      <TableHead>评分</TableHead>
                      <TableHead>投标金额</TableHead>
                      <TableHead>周期</TableHead>
                      <TableHead>投标数</TableHead>
                      <TableHead>成功率</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {competitorsLoading ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-8">
                          <Loader2 className="h-4 w-4 animate-spin inline-block" /> 加载中...
                        </TableCell>
                      </TableRow>
                    ) : competitors.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                          暂无数据，请选择项目进行分析
                        </TableCell>
                      </TableRow>
                    ) : (
                      competitors.map((competitor) => (
                        <TableRow key={competitor.bidder_id}>
                          <TableCell className="font-medium">{competitor.bidder_name}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <span className="text-yellow-500">★</span>
                              {competitor.rating}
                            </div>
                          </TableCell>
                          <TableCell className="font-mono">${competitor.amount}</TableCell>
                          <TableCell>{competitor.period}天</TableCell>
                          <TableCell>{competitor.bid_count}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Progress value={competitor.success_rate} className="h-2 w-16" />
                              <span className="text-xs">{competitor.success_rate}%</span>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Competitors Dialog */}
      <Dialog open={showCompetitors} onOpenChange={setShowCompetitors}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>竞品分析</DialogTitle>
            <DialogDescription>{selectedProposal?.project_title}</DialogDescription>
          </DialogHeader>
          {competitorsLoading ? (
            <div className="flex justify-center py-10">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50">
                  <TableHead>竞标者</TableHead>
                  <TableHead>评分</TableHead>
                  <TableHead>投标金额</TableHead>
                  <TableHead>周期</TableHead>
                  <TableHead>成功率</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {competitors.map((competitor) => (
                  <TableRow key={competitor.bidder_id}>
                    <TableCell className="font-medium">{competitor.bidder_name}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <span className="text-yellow-500">★</span>
                        {competitor.rating}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono">${competitor.amount}</TableCell>
                    <TableCell>{competitor.period}天</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Progress value={competitor.success_rate} className="h-2 w-16" />
                        <span className="text-xs">{competitor.success_rate}%</span>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCompetitors(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit Template Dialog */}
      <Dialog open={showTemplateDialog} onOpenChange={(open) => {
        if (!open) {
          handleCloseTemplateDialog();
        }
        setShowTemplateDialog(open);
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingTemplate ? '编辑模板' : '创建提案模板'}</DialogTitle>
            <DialogDescription>
              {editingTemplate ? '修改提案模板内容' : '添加新的提案模板以便快速投标'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="name">模板名称</Label>
              <Input
                id="name"
                value={newTemplate.name}
                onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })}
                placeholder="例如：Web开发通用模板"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="content">模板内容</Label>
              <Textarea
                id="content"
                value={newTemplate.content}
                onChange={(e) => setNewTemplate({ ...newTemplate, content: e.target.value })}
                placeholder="输入提案模板内容..."
                rows={6}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="skills">相关技能 (逗号分隔)</Label>
              <Input
                id="skills"
                value={newTemplate.skills}
                onChange={(e) => setNewTemplate({ ...newTemplate, skills: e.target.value })}
                placeholder="例如：React, Node.js, Python"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={handleCloseTemplateDialog}>
              取消
            </Button>
            <Button
              onClick={handleSaveTemplate}
              disabled={!newTemplate.name || !newTemplate.content || createTemplateMutation.isPending || updateTemplateMutation.isPending}
            >
              {(createTemplateMutation.isPending || updateTemplateMutation.isPending) && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              <Save className="mr-2 h-4 w-4" />
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
