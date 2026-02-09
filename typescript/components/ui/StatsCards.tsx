import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Stats } from '@/lib/types';
import { BarChart3, Clock, DollarSign, Target } from 'lucide-react';

interface StatsCardsProps {
  stats?: Stats;
  isLoading: boolean;
}

export function StatsCards({ stats, isLoading }: StatsCardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <div className="h-4 w-24 bg-gray-200 rounded"></div>
            </CardHeader>
            <CardContent>
              <div className="h-8 w-16 bg-gray-200 rounded"></div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const displayStats = stats || {
    total_projects: 0,
    today_new: 0,
    avg_score: 0,
    pending_bids: 0,
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总项目数</CardTitle>
          <BarChart3 className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{displayStats.total_projects}</div>
          <p className="text-xs text-muted-foreground">历史累计抓取</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">今日新增</CardTitle>
          <Clock className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{displayStats.today_new}</div>
          <p className="text-xs text-muted-foreground">24小时内更新</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">平均评分</CardTitle>
          <Target className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{displayStats.avg_score?.toFixed(1) || 'N/A'}</div>
                  <p className="text-xs text-muted-foreground">AI 质量评分</p>
                </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">待处理投标</CardTitle>
          <DollarSign className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{displayStats.pending_bids}</div>
          <p className="text-xs text-muted-foreground">等待响应中</p>
        </CardContent>
      </Card>
    </div>
  );
}
