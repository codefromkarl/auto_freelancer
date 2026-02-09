'use client';

import { Pie, PieChart, ResponsiveContainer, Cell, Tooltip, Legend } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface BudgetDistributionChartProps {
  data?: Array<{ name: string; value: number }>;
}

const defaultData = [
  { name: '< $100', value: 0 },
  { name: '$100 - $500', value: 0 },
  { name: '$500 - $1000', value: 0 },
  { name: '> $1000', value: 0 },
];

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042'];

export function BudgetDistributionChart({ data = defaultData }: BudgetDistributionChartProps) {
  const chartData = data.length > 0 ? data : defaultData;
  const hasData = chartData.some(d => d.value > 0);

  return (
    <Card className="col-span-1">
      <CardHeader>
        <CardTitle>预算分布</CardTitle>
        <CardDescription>项目预算区间占比 (USD)</CardDescription>
      </CardHeader>
      <CardContent className="h-[300px]">
        {hasData ? (
          <ResponsiveContainer width="100%" height={300} minWidth={0} minHeight={0}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                fill="#8884d8"
                paddingAngle={5}
                dataKey="value"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400 text-sm">
            无可用数据
          </div>
        )}
      </CardContent>
    </Card>
  );
}
