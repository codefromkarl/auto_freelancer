'use client';

import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface ScoreDistributionChartProps {
  data?: Array<{ range: string; count: number }>;
}

const defaultData = [
  { range: '0-2', count: 0 },
  { range: '2-4', count: 0 },
  { range: '4-6', count: 0 },
  { range: '6-8', count: 0 },
  { range: '8-10', count: 0 },
];

export function ScoreDistributionChart({ data = defaultData }: ScoreDistributionChartProps) {
  return (
    <Card className="col-span-1">
      <CardHeader>
        <CardTitle>AI 评分分布</CardTitle>
        <CardDescription>最近抓取项目的质量评分分布情况</CardDescription>
      </CardHeader>
      <CardContent className="h-[300px]">
        <ResponsiveContainer width="100%" height={300} minWidth={0} minHeight={0}>
          <BarChart data={data.length > 0 ? data : defaultData}>
            <XAxis
              dataKey="range"
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => `${value}`}
            />
            <Tooltip />
            <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} name="项目数量" />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
