'use client';

import { useState } from 'react';
import { Shield, AlertTriangle, CheckCircle, Search, Eye, Filter } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// Mock Data
const MOCK_RISKS = [
  {
    id: 101,
    clientName: 'John Doe',
    clientId: 4521,
    country: 'US',
    riskScore: 85,
    status: 'high',
    flags: ['Payment Unverified', 'Low Hire Rate'],
    lastAssessed: '2024-05-20 10:30',
  },
  {
    id: 102,
    clientName: 'Alice Smith',
    clientId: 8823,
    country: 'UK',
    riskScore: 12,
    status: 'low',
    flags: [],
    lastAssessed: '2024-05-20 11:15',
  },
  {
    id: 103,
    clientName: 'Tech Corp',
    clientId: 9912,
    country: 'IN',
    riskScore: 65,
    status: 'medium',
    flags: ['No Deposit'],
    lastAssessed: '2024-05-19 16:45',
  },
];

export default function RiskPage() {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedRisk, setSelectedRisk] = useState<any>(null);
  const [filterStatus, setFilterStatus] = useState('all');

  const filteredRisks = MOCK_RISKS.filter((risk) => {
    const matchesSearch =
      risk.clientName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      risk.clientId.toString().includes(searchTerm);
    const matchesStatus = filterStatus === 'all' || risk.status === filterStatus;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">客户风险管理</h1>
        <p className="text-gray-500">监控和评估客户风险等级</p>
      </div>

      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
        <div className="relative w-full md:w-96">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 h-4 w-4" />
          <Input
            placeholder="搜索客户名或 ID..."
            className="pl-9"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="flex gap-3 w-full md:w-auto">
          <Select value={filterStatus} onValueChange={setFilterStatus}>
            <SelectTrigger className="w-[150px]">
              <SelectValue placeholder="风险等级" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部等级</SelectItem>
              <SelectItem value="high">高风险</SelectItem>
              <SelectItem value="medium">中风险</SelectItem>
              <SelectItem value="low">低风险</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" className="gap-2">
            <Filter className="h-4 w-4" />
            更多筛选
          </Button>
        </div>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">高风险拦截</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">12</div>
            <p className="text-xs text-gray-500 mt-1">本周拦截的高风险客户</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">平均风险分</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-gray-900">45.2</div>
            <p className="text-xs text-gray-500 mt-1">基于最近 100 次评估</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-500">安全通过率</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">78%</div>
            <p className="text-xs text-gray-500 mt-1">低风险客户占比</p>
          </CardContent>
        </Card>
      </div>

      {/* Risks Table */}
      <Card>
        <CardHeader>
          <CardTitle>最近评估记录</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>客户信息</TableHead>
                <TableHead>国家</TableHead>
                <TableHead>风险评分</TableHead>
                <TableHead>触发规则</TableHead>
                <TableHead>评估时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRisks.map((risk) => (
                <TableRow key={risk.id}>
                  <TableCell>
                    <div className="font-medium">{risk.clientName}</div>
                    <div className="text-xs text-gray-500">ID: {risk.clientId}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{risk.country}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span
                        className={`font-bold ${
                          risk.riskScore >= 80
                            ? 'text-red-600'
                            : risk.riskScore >= 50
                              ? 'text-yellow-600'
                              : 'text-green-600'
                        }`}
                      >
                        {risk.riskScore}
                      </span>
                      <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            risk.riskScore >= 80
                              ? 'bg-red-500'
                              : risk.riskScore >= 50
                                ? 'bg-yellow-500'
                                : 'bg-green-500'
                          }`}
                          style={{ width: `${risk.riskScore}%` }}
                        />
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {risk.flags.length > 0 ? (
                        risk.flags.map((flag, idx) => (
                          <Badge
                            key={idx}
                            variant="outline"
                            className="text-xs text-red-500 border-red-200 bg-red-50"
                          >
                            {flag}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-gray-400">无</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-gray-500 text-sm">{risk.lastAssessed}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => setSelectedRisk(risk)}>
                      <Eye className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Detail Dialog */}
      <Dialog open={!!selectedRisk} onOpenChange={(open) => !open && setSelectedRisk(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>风险评估详情</DialogTitle>
            <DialogDescription>
              客户 {selectedRisk?.clientName} (ID: {selectedRisk?.clientId}) 的详细分析报告
            </DialogDescription>
          </DialogHeader>

          {selectedRisk && (
            <div className="space-y-6 py-4">
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border">
                <div>
                  <div className="text-sm text-gray-500">综合风险评分</div>
                  <div className="text-3xl font-bold mt-1">{selectedRisk.riskScore}/100</div>
                </div>
                <div
                  className={`px-4 py-2 rounded-lg font-bold text-white ${
                    selectedRisk.riskScore >= 80
                      ? 'bg-red-500'
                      : selectedRisk.riskScore >= 50
                        ? 'bg-yellow-500'
                        : 'bg-green-500'
                  }`}
                >
                  {selectedRisk.riskScore >= 80
                    ? '高风险'
                    : selectedRisk.riskScore >= 50
                      ? '中风险'
                      : '低风险'}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-2 flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-orange-500" />
                  风险因素分析
                </h3>
                <div className="space-y-2">
                  {selectedRisk.flags.length > 0 ? (
                    selectedRisk.flags.map((flag: string, idx: number) => (
                      <div
                        key={idx}
                        className="flex items-center gap-2 text-sm text-gray-700 p-2 bg-red-50 rounded border border-red-100"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                        {flag}
                      </div>
                    ))
                  ) : (
                    <div className="text-sm text-gray-500 italic">未发现明显风险因素</div>
                  )}
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-2 flex items-center gap-2">
                  <Shield className="h-4 w-4 text-blue-500" />
                  AI 建议
                </h3>
                <div className="p-3 bg-blue-50 text-blue-800 text-sm rounded-lg leading-relaxed">
                  基于当前评估结果，建议{selectedRisk.riskScore >= 80 ? '拒绝合作' : '谨慎接触'}。
                  {selectedRisk.flags.includes('Payment Unverified') &&
                    '请注意该客户尚未验证支付方式，存在付款风险。'}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
