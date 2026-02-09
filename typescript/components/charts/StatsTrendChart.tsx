'use client';

import {
  Line,
  LineChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const data = [
  { date: '1/1', new: 12, bid: 2 },
  { date: '1/2', new: 19, bid: 5 },
  { date: '1/3', new: 30, bid: 8 },
  { date: '1/4', new: 25, bid: 6 },
  { date: '1/5', new: 40, bid: 10 },
  { date: '1/6', new: 35, bid: 9 },
  { date: '1/7', new: 50, bid: 15 },
];

export function StatsTrendChart() {
  return (
    <Card className="col-span-1 md:col-span-2">
      <CardHeader>
        <CardTitle>每日趋势</CardTitle>
        <CardDescription>每日新增项目与自动投标数量</CardDescription>
      </CardHeader>
      <CardContent className="h-[300px]">
        <ResponsiveContainer width="100%" height={300} minWidth={0} minHeight={0}>
          <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              stroke="#888888"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="new"
              stroke="#3b82f6"
              strokeWidth={2}
              name="新增项目"
              activeDot={{ r: 8 }}
            />
            <Line type="monotone" dataKey="bid" stroke="#8b5cf6" strokeWidth={2} name="发送投标" />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
