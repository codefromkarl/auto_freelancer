'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStats, searchProjects } from '@/lib/api';
import Link from 'next/link';
import { ArrowRight, RotateCw, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatsCards } from '@/components/ui/StatsCards';
import { ProjectCard } from '@/components/ui/ProjectCard';
import { ScoreDistributionChart } from '@/components/charts/ScoreDistributionChart';
import { BudgetDistributionChart } from '@/components/charts/BudgetDistributionChart';
import { StatsTrendChart } from '@/components/charts/StatsTrendChart';
import { ApiErrorDisplay } from '@/components/ui/ErrorBoundary';

export default function Home() {
  const [statsError, setStatsError] = useState<string | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);

  const {
    data: stats,
    isLoading: statsLoading,
    refetch: refetchStats,
    isError: statsIsError,
    error: statsErrorObj,
  } = useQuery({
    queryKey: ['stats'],
    queryFn: getStats,
    retry: 1,
    refetchOnWindowFocus: false,
  });

  const {
    data: recentProjectsData,
    isLoading: projectsLoading,
    refetch: refetchProjects,
    isError: projectsIsError,
    error: projectsErrorObj,
  } = useQuery({
    queryKey: ['recentProjects'],
    queryFn: () => searchProjects({ status: 'active', query: '' }),
    retry: 1,
    refetchOnWindowFocus: false,
  });

  // Extract data array from response object
  const recentProjects = recentProjectsData?.data || [];

  // Update error states when queries fail
  const handleRefresh = async () => {
    setStatsError(null);
    setProjectsError(null);
    try {
      await refetchStats();
    } catch {
      setStatsError('统计信息加载失败');
    }
    try {
      await refetchProjects();
    } catch {
      setProjectsError('项目列表加载失败');
    }
  };

  // Determine error messages
  const getErrorMessage = (error: unknown): string => {
    if (error instanceof Error) {
      return error.message || '加载失败，请稍后重试';
    }
    return '加载失败，请稍后重试';
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">Dashboard</h1>
          <p className="text-muted-foreground mt-1">这里是今日的自动化概况与核心指标。</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={statsLoading || projectsLoading}
          >
            <RotateCw
              className={`mr-2 h-4 w-4 ${statsLoading || projectsLoading ? 'animate-spin' : ''}`}
            />
            刷新数据
          </Button>
          <Button asChild size="sm">
            <Link href="/projects">浏览项目</Link>
          </Button>
        </div>
      </div>

      {/* Stats Cards - with error handling */}
      {statsIsError ? (
        <ApiErrorDisplay
          message={statsError || getErrorMessage(statsErrorObj)}
          onRetry={handleRefresh}
          isLoading={statsLoading}
        />
      ) : (
        <StatsCards stats={stats} isLoading={statsLoading} />
      )}

      {/* Charts Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsTrendChart />
        <ScoreDistributionChart data={stats?.score_distribution} />
        <BudgetDistributionChart data={stats?.budget_distribution} />
      </div>

      {/* Recent Projects */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-2xl font-semibold tracking-tight">最新活跃项目</h2>
          <Button variant="ghost" asChild className="gap-1">
            <Link href="/projects">
              查看全部 <ArrowRight size={16} />
            </Link>
          </Button>
        </div>

        {projectsIsError ? (
          <ApiErrorDisplay
            message={projectsError || getErrorMessage(projectsErrorObj)}
            onRetry={handleRefresh}
            isLoading={projectsLoading}
          />
        ) : projectsLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-48 bg-gray-100 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {recentProjects?.slice(0, 6).map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
            {recentProjects.length === 0 && (
              <div className="col-span-full py-12 text-center text-muted-foreground bg-gray-50 rounded-xl border border-dashed border-gray-200">
                <div className="flex flex-col items-center gap-2">
                  <WifiOff className="w-8 h-8 text-gray-400" />
                  <p>暂无项目数据</p>
                  <p className="text-xs text-gray-400">请确保后端服务正在运行并已抓取项目数据</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
