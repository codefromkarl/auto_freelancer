'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  searchProjects,
  scoreProject,
  batchScoreProjects,
  flagProject,
  archiveProject,
  exportProjects,
} from '@/lib/api';
import Link from 'next/link';
import {
  Search,
  Filter,
  ArrowUpRight,
  Star,
  Flag,
  Archive,
  Download,
  CheckSquare,
  Square,
  MoreHorizontal,
  RefreshCw,
  CloudDownload,
  Plus,
  Brain,
  FileText,
  Globe,
  Tags,
  WifiOff,
} from 'lucide-react';
import { useDebounce } from '@/lib/hooks';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { ProjectFilters } from '@/lib/types';
import { ApiErrorDisplay } from '@/components/ui/ErrorBoundary';

const AVAILABLE_SKILLS = [
  'Python',
  'JavaScript',
  'React',
  'Node.js',
  'TypeScript',
  'Vue',
  'Go',
  'Rust',
  'Java',
  'C++',
  'AWS',
  'Docker',
  'Kubernetes',
  'ML',
];

const COUNTRIES = [
  'United States',
  'United Kingdom',
  'Canada',
  'Australia',
  'Germany',
  'France',
  'India',
  'Brazil',
  'Netherlands',
  'Spain',
];

export default function ProjectsPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedProjects, setSelectedProjects] = useState<number[]>([]);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [exportFormat, setExportFormat] = useState<'csv' | 'xlsx' | 'json'>('csv');

  // Advanced filters
  const [minScore, setMinScore] = useState(0);
  const [maxScore, setMaxScore] = useState(10);
  const [status, setStatus] = useState('active');
  const [country, setCountry] = useState('');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [budgetMin, setBudgetMin] = useState('');
  const [budgetMax, setBudgetMax] = useState('');
  const [isSyncing, setIsSyncing] = useState(false);

  const debouncedQuery = useDebounce(searchQuery, 500);
  const queryClient = useQueryClient();

  const filters: ProjectFilters = {
    query: debouncedQuery,
    min_score: minScore,
    status: status === 'all' ? '' : status,
    country: country || undefined,
    skills: selectedSkills.length > 0 ? selectedSkills : undefined,
    score_range: [minScore, maxScore],
    budget_min: budgetMin ? parseInt(budgetMin) : undefined,
    budget_max: budgetMax ? parseInt(budgetMax) : undefined,
  };

  const {
    data: responseData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['projects', filters],
    queryFn: () => searchProjects(filters),
    placeholderData: (previousData) => previousData,
    retry: 1,
    refetchOnWindowFocus: false,
    // 如果正在同步，每5秒轮询一次状态
    refetchInterval: (data: any) => (data?.is_syncing ? 5000 : false),
  });

  const projects = responseData?.data || [];
  const isBackendSyncing = responseData?.is_syncing || false;

  const batchScoreMutation = useMutation({
    mutationFn: () => batchScoreProjects(selectedProjects),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setSelectedProjects([]);
    },
  });

  const scoreMutation = useMutation({
    mutationFn: (id: number) => scoreProject(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const flagMutation = useMutation({
    mutationFn: ({ id, flag }: { id: number; flag: boolean }) => flagProject(id, flag),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: ({ id, archive }: { id: number; archive: boolean }) => archiveProject(id, archive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  const toggleSelectAll = () => {
    if (selectedProjects.length === projects?.length) {
      setSelectedProjects([]);
    } else {
      setSelectedProjects(projects?.map((p) => p.id) || []);
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedProjects((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  const handleExport = async () => {
    const blob = await exportProjects({
      format: exportFormat,
      fields: ['title', 'budget_minimum', 'budget_maximum', 'ai_score', 'country', 'status'],
      filters: filters,
    });

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `projects_export.${exportFormat}`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    setShowExportDialog(false);
  };

  const getScoreColor = (score: number) => {
    if (score >= 8) return 'text-green-600';
    if (score >= 5) return 'text-orange-600';
    return 'text-muted-foreground';
  };

  const handleRefresh = () => {
    refetch();
  };

  const handleSync = async () => {
    if (isSyncing) return;
    setIsSyncing(true);
    try {
      await searchProjects({ ...filters, refresh: true });
      refetch();
      alert('同步成功！');
    } catch (err) {
      alert('同步失败: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSyncing(false);
    }
  };

  const getErrorMessage = (error: unknown): string => {
    if (error instanceof Error) {
      return error.message || '加载失败，请稍后重试';
    }
    return '加载失败，请稍后重试';
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">项目列表</h1>
          <p className="text-muted-foreground mt-1">管理和筛选抓取到的 Freelancer 项目</p>
        </div>
        <div className="flex gap-2">
          <Button 
            variant="default" 
            size="sm" 
            onClick={handleSync} 
            disabled={isSyncing || isBackendSyncing}
            className="bg-blue-600 hover:bg-blue-700 text-white min-w-[100px]"
          >
            <CloudDownload className={`mr-2 h-4 w-4 ${isSyncing || isBackendSyncing ? 'animate-spin' : ''}`} />
            {isSyncing || isBackendSyncing ? '同步中...' : '同步项目'}
          </Button>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isFetching}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowExportDialog(true)}>
            <Download className="mr-2 h-4 w-4" />
            导出
          </Button>
        </div>
      </div>

      {/* Filters Bar */}
      <Card className="p-4">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col md:flex-row gap-4 items-center">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground w-4 h-4" />
              <Input
                placeholder="搜索项目标题或描述..."
                className="pl-9"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            <div className="flex flex-col sm:flex-row gap-4 w-full md:w-auto">
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="状态" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">状态: 开放</SelectItem>
                  <SelectItem value="fetched">状态: 已抓取</SelectItem>
                  <SelectItem value="all">状态: 全部</SelectItem>
                </SelectContent>
              </Select>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
              >
                <Filter className="mr-2 h-4 w-4" />
                高级筛选
              </Button>
            </div>
          </div>

          {/* Advanced Filters */}
          {showAdvancedFilters && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-4 border-t">
              <div className="space-y-2">
                <label className="text-sm font-medium">评分范围</label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min="0"
                    max="10"
                    value={minScore}
                    onChange={(e) => setMinScore(parseFloat(e.target.value))}
                    className="w-20"
                  />
                  <span>-</span>
                  <Input
                    type="number"
                    min="0"
                    max="10"
                    value={maxScore}
                    onChange={(e) => setMaxScore(parseFloat(e.target.value))}
                    className="w-20"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-1">
                  <Globe className="h-4 w-4" /> 国家
                </label>
                <Select value={country} onValueChange={setCountry}>
                  <SelectTrigger>
                    <SelectValue placeholder="选择国家" />
                  </SelectTrigger>
                  <SelectContent>
                    {COUNTRIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-1">
                  <Tags className="h-4 w-4" /> 技能
                </label>
                <Select
                  value={selectedSkills[0] || ''}
                  onValueChange={(v) => {
                    if (v && !selectedSkills.includes(v)) {
                      setSelectedSkills([...selectedSkills, v]);
                    }
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="添加技能" />
                  </SelectTrigger>
                  <SelectContent>
                    {AVAILABLE_SKILLS.filter((s) => !selectedSkills.includes(s)).map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedSkills.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {selectedSkills.map((s) => (
                      <Badge key={s} variant="secondary" className="text-xs">
                        {s}
                        <button
                          onClick={() => setSelectedSkills(selectedSkills.filter((sk) => sk !== s))}
                          className="ml-1 hover:text-red-500"
                        >
                          ×
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">预算范围 (USD)</label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    placeholder="最低"
                    value={budgetMin}
                    onChange={(e) => setBudgetMin(e.target.value)}
                    className="w-24"
                  />
                  <span>-</span>
                  <Input
                    type="number"
                    placeholder="最高"
                    value={budgetMax}
                    onChange={(e) => setBudgetMax(e.target.value)}
                    className="w-24"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Bulk Actions Bar */}
      {selectedProjects.length > 0 && (
        <Card className="p-3 bg-blue-50 border-blue-200">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-blue-700">
              已选择 {selectedProjects.length} 个项目
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => batchScoreMutation.mutate()}
                disabled={batchScoreMutation.isPending}
              >
                <Star className="mr-2 h-4 w-4" />
                {batchScoreMutation.isPending ? '评分中...' : '批量评分'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  selectedProjects.forEach((id) => flagMutation.mutate({ id, flag: true }));
                }}
              >
                <Flag className="mr-2 h-4 w-4" />
                标记
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  selectedProjects.forEach((id) => archiveMutation.mutate({ id, archive: true }));
                }}
              >
                <Archive className="mr-2 h-4 w-4" />
                归档
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelectedProjects([])}>
                取消选择
              </Button>
            </div>
          </div>
        </Card>
      )}

      {/* Projects Table */}
      <div className="rounded-md border bg-white overflow-hidden shadow-sm">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead className="w-[40px]">
                <Checkbox
                  checked={projects?.length === selectedProjects.length && projects?.length > 0}
                  onCheckedChange={toggleSelectAll}
                />
              </TableHead>
              <TableHead className="w-[40%]">项目名称</TableHead>
              <TableHead>预算</TableHead>
              <TableHead>技能</TableHead>
              <TableHead>AI评分</TableHead>
              <TableHead>国家</TableHead>
              <TableHead>提交时间</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {/* Error state */}
            {isError ? (
              <TableRow>
                <TableCell colSpan={10} className="h-48">
                  <ApiErrorDisplay
                    message={getErrorMessage(error)}
                    onRetry={handleRefresh}
                    isLoading={isLoading}
                  />
                </TableCell>
              </TableRow>
            ) : isLoading ? (
              <TableRow>
                <TableCell colSpan={10} className="h-24 text-center">
                  <div className="flex items-center justify-center gap-2 text-muted-foreground">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    加载中...
                  </div>
                </TableCell>
              </TableRow>
            ) : projects?.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="h-24 text-center">
                  <div className="flex flex-col items-center gap-2 text-muted-foreground py-4">
                    <WifiOff className="h-8 w-8 text-gray-400" />
                    <p>没有找到符合条件的项目</p>
                    <p className="text-xs text-gray-400">尝试调整筛选条件或刷新数据</p>
                    <Button variant="outline" size="sm" onClick={handleRefresh} className="mt-2">
                      <RefreshCw className="mr-2 h-4 w-4" />
                      刷新数据
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              projects?.map((project) => (
                <TableRow key={project.id} className="group">
                  <TableCell>
                    <Checkbox
                      checked={selectedProjects.includes(project.id)}
                      onCheckedChange={() => toggleSelect(project.id)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {project.is_flagged && (
                        <Flag className="h-4 w-4 text-yellow-500 fill-yellow-500" />
                      )}
                      <div>
                        <div
                          className="font-medium text-foreground line-clamp-1"
                          title={project.title}
                        >
                          <Link href={`/projects/${project.id}`} className="hover:underline">
                            {project.title}
                          </Link>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1 line-clamp-1">
                          {project.description?.substring(0, 80)}...
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap font-mono text-xs">
                    {project.currency_code} {project.budget_minimum} - {project.budget_maximum}
                  </TableCell>
                  <TableCell className="max-w-[200px]">
                    <div className="flex flex-wrap gap-1">
                      {(() => {
                        try {
                          const skills = typeof project.skills === 'string' 
                            ? JSON.parse(project.skills) 
                            : (Array.isArray(project.skills) ? project.skills : []);
                          
                          // If skills are just IDs (numbers), we might not be able to show names without a mapping.
                          // Assuming for now they might be names or we handle it.
                          // If they are numbers, we'll just show IDs or nothing.
                          return Array.isArray(skills) ? skills.slice(0, 3).map((s: any, i: number) => (
                            <Badge key={i} variant="outline" className="text-[10px] px-1 py-0 h-4">
                              {s}
                            </Badge>
                          )) : null;
                        } catch (e) {
                          return null;
                        }
                      })()}
                    </div>
                  </TableCell>
                  <TableCell>
                    {project.ai_score !== null && project.ai_score !== undefined ? (
                      <div className="flex items-center gap-1 font-bold">
                        <span className={getScoreColor(project.ai_score)}>
                          {project.ai_score.toFixed(1)}
                        </span>
                        <span className="text-gray-300 text-[10px]">/10</span>
                      </div>
                    ) : (
                      <Button 
                        size="sm" 
                        variant="ghost" 
                        className="h-7 text-xs text-blue-500 hover:text-blue-600 p-0"
                        onClick={() => scoreMutation.mutate(project.id)}
                        disabled={scoreMutation.isPending && scoreMutation.variables === project.id}
                      >
                        {scoreMutation.isPending && scoreMutation.variables === project.id ? (
                          <RefreshCw className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <Plus className="h-3 w-3 mr-1" />
                        )}
                        分析
                      </Button>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                     <div className="flex items-center gap-1">
                        <Globe className="h-3 w-3" />
                        {project.country || '-'}
                     </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                    {new Date(project.submitdate || '').toLocaleDateString()}
                  </TableCell>
                  <TableCell>
                    <Badge variant={project.status === 'active' ? 'default' : 'secondary'}>
                      {project.status === 'active' ? '开放' : project.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button 
                        variant="ghost" 
                        size="icon"
                        onClick={() => scoreMutation.mutate(project.id)}
                        disabled={scoreMutation.isPending && scoreMutation.variables === project.id}
                        title="AI 分析"
                      >
                        <Brain className={`h-4 w-4 text-blue-500 ${scoreMutation.isPending && scoreMutation.variables === project.id ? 'animate-spin' : ''}`} />
                      </Button>
                      <Button variant="ghost" size="icon" asChild>
                        <Link href={`/projects/${project.id}`} title="查看详情">
                          <ArrowUpRight className="h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Export Dialog */}
      <Dialog open={showExportDialog} onOpenChange={setShowExportDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>导出项目</DialogTitle>
            <DialogDescription>选择导出格式和包含的字段</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">导出格式</label>
              <div className="flex gap-2">
                {(['csv', 'xlsx', 'json'] as const).map((format) => (
                  <Button
                    key={format}
                    variant={exportFormat === format ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setExportFormat(format)}
                  >
                    {format.toUpperCase()}
                  </Button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowExportDialog(false)}>
              取消
            </Button>
            <Button onClick={handleExport}>
              <Download className="mr-2 h-4 w-4" />
              导出
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
