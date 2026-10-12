'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getWorkflow,
  getWorkflowStats,
  syncWorkflow,
  decideWorkflow,
  resolveWorkflow,
} from '@/lib/api';
import type { WorkflowCandidate, WorkflowState } from '@/lib/types';
import { Button } from '@/components/ui/button';

const labels: Record<WorkflowState, string> = {
  needs_evaluation: '待判断',
  needs_clarification: '待澄清',
  ready: '可准备',
  awaiting_approval: '待审批',
  deferred: '暂缓',
  rejected: '已拒绝',
  submitted: '已投标',
  outcome_unknown: '结果待核实',
};
const stageLabels: Record<string, string> = {
  fetch: '抓取',
  filter: '初筛',
  score: '评分',
  competition: '竞争资料',
  queue: '候选流转',
  clarification: '澄清',
  preparation: '标书准备',
  approval: '审批',
  submission: '投标',
  notification: '通知',
};

const resultLabels: Record<string, string> = {
  observed: '读取',
  excluded: '排除',
  kept: '保留',
  scored: '评分完成',
  failed: '失败',
  attempted: '提交核验尝试',
  prepared: '准备完成',
  answered: '信息已补充',
  approved: '已批准',
  confirmed: '已确认发送',
};
const reasonLabels: Record<string, string> = {
  new_project: '新项目',
  scope_changed: '需求变化',
  score_stale: '评分需更新',
  scope_unknown: '范围待明确',
  scored: '等待可行性检查',
  eligible: '符合准备条件',
  score_below_threshold: '评分低于阈值',
  low_net_hourly: '净时薪不足',
  scope_too_large: '工时超限',
  payment_unverified: '付款未验证',
  currency_unknown: '汇率待核实',
  terms_invalid: '条款需复核',
  preparation_failed: '标书准备失败',
  operator_deferred: '人工暂缓',
  operator_rejected: '人工拒绝',
  operator_resumed: '人工恢复',
  defer_elapsed: '再次检查时间已到',
  clarification_answered: '答复已录入',
  approval_rejected: '审批拒绝',
  approval_expired: '批准过期',
  approval_blocked: '执行核验未通过',
  not_biddable: '项目状态不可投标',
  filtered_budget: '预算不足',
  filtered_desc: '描述不足',
  filtered_status: '项目状态',
  filtered_skill: '能力不匹配',
  filtered_time: '发布时间',
  filtered_billing_type: '计费类型',
  filtered_data: '数据待核实',
  invalid_input_or_model_result: '输入或模型结果不完整',
  invalid_terms: '报价或工时不合格',
  no_model_provider: '未配置评分模型',
  prepared: '等待审批',
  bid_recorded: '已有投标',
  submitted: '已确认提交',
  outcome_unknown: '结果待核实',
};

function Candidate({ item }: { item: WorkflowCandidate }) {
  const client = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [reason, setReason] = useState('');
  const [resumeAt, setResumeAt] = useState('');
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['workflow'] });
    void client.invalidateQueries({ queryKey: ['workflow-stats'] });
  };
  const decision = useMutation({
    mutationFn: (action: 'defer' | 'reject' | 'resume') =>
      decideWorkflow(
        item.project_id,
        item.revision,
        action,
        reason,
        action === 'defer' && resumeAt ? new Date(resumeAt).toISOString() : undefined
      ),
    onSuccess: refresh,
    retry: false,
  });
  const resolve = useMutation({
    mutationFn: () =>
      resolveWorkflow(
        item.project_id,
        item.revision,
        item.questions.map((q) => ({ id: q.id, answer: answers[q.id] || '' }))
      ),
    onSuccess: refresh,
    retry: false,
  });
  const busy = decision.isPending || resolve.isPending;
  const terminal = item.state === 'submitted' || item.state === 'outcome_unknown';
  const error = decision.error || resolve.error;
  return (
    <details className="border-b border-gray-200 py-4">
      <summary className="cursor-pointer list-none rounded-sm focus-visible:outline-2 focus-visible:outline-blue-600">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-3xl">
            <p className="font-semibold text-gray-900">{item.title}</p>
            <p className="mt-1 text-sm text-gray-600">{item.reason}</p>
          </div>
          <div className="flex items-center gap-4 text-sm">
            {item.ai_score !== null && <span>评分 {item.ai_score.toFixed(1)}</span>}
            <span
              className={
                item.state === 'needs_clarification'
                  ? 'font-medium text-amber-700'
                  : 'font-medium text-blue-700'
              }
            >
              {labels[item.state]}
            </span>
          </div>
        </div>
      </summary>
      <div className="mt-5 max-w-3xl space-y-4">
        <Link
          className="text-sm text-blue-700 underline underline-offset-4"
          href={`/projects/${item.project_id}`}
        >
          打开项目与标书
        </Link>
        {item.resume_at && (
          <p className="text-sm">再次检查：{new Date(item.resume_at).toLocaleString()}</p>
        )}
        {item.state === 'needs_clarification' && item.questions.length > 0 && (
          <div className="space-y-3 border-l-2 border-amber-600 pl-4">
            <p className="text-sm text-gray-600">
              填写已核实信息，或明确写出假设。保存后会重新评估工时和报价，不会发送客户消息。
            </p>
            {item.questions.map((q) => (
              <label key={q.id} className="block text-sm font-medium">
                {q.question}
                <textarea
                  className="mt-2 block w-full rounded-md border border-gray-300 bg-white p-3 font-normal focus:outline-blue-600"
                  rows={3}
                  value={answers[q.id] || ''}
                  maxLength={2000}
                  disabled={busy}
                  onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                />
              </label>
            ))}
            {item.state === 'needs_clarification' && (
              <Button
                disabled={busy || item.questions.some((q) => !answers[q.id]?.trim())}
                onClick={() => resolve.mutate()}
              >
                保存答复，等待重新评估
              </Button>
            )}
          </div>
        )}
        {item.answers.length > 0 && (
          <div className="space-y-2 text-sm text-gray-700">
            <p className="font-medium">已录入的范围信息</p>
            {item.answers.map((a) => (
              <p key={a.id}>
                <span className="font-medium">{a.question}</span>
                <br />
                {a.answer}
              </p>
            ))}
          </div>
        )}
        {!terminal && (
          <div className="space-y-3">
            <label className="block text-sm font-medium">
              处理原因
              <textarea
                className="mt-2 block w-full rounded-md border border-gray-300 bg-white p-3 font-normal focus:outline-blue-600"
                rows={2}
                aria-label="处理原因"
                maxLength={1000}
                value={reason}
                disabled={busy}
                onChange={(e) => setReason(e.target.value)}
                placeholder="例如：本周没有可用时间，或预算无法覆盖范围"
              />
            </label>
            <label className="block text-sm">
              暂缓后再次检查时间（可选）
              <input
                type="datetime-local"
                className="ml-3 rounded-md border border-gray-300 p-2"
                value={resumeAt}
                disabled={busy}
                onChange={(e) => setResumeAt(e.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={busy || !reason.trim()}
                onClick={() => decision.mutate('defer')}
              >
                暂缓
              </Button>
              <Button
                variant="outline"
                disabled={busy || !reason.trim()}
                onClick={() => decision.mutate('reject')}
              >
                拒绝此候选
              </Button>
              {['deferred', 'rejected'].includes(item.state) && (
                <Button disabled={busy || !reason.trim()} onClick={() => decision.mutate('resume')}>
                  恢复并重新评估
                </Button>
              )}
            </div>
          </div>
        )}
        {terminal && (
          <p className="text-sm text-gray-600">提交记录由投标链路核实，不能通过队列恢复或重发。</p>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {error.message}。输入已保留；版本冲突时请刷新列表。
          </p>
        )}
      </div>
    </details>
  );
}

export default function WorkflowPage() {
  const [state, setState] = useState<WorkflowState | undefined>();
  const [offset, setOffset] = useState(0);
  const client = useQueryClient();
  const queue = useQuery({
    queryKey: ['workflow', state, offset],
    queryFn: () => getWorkflow(state, offset),
  });
  const stats = useQuery({ queryKey: ['workflow-stats'], queryFn: getWorkflowStats });
  const sync = useMutation({
    mutationFn: syncWorkflow,
    retry: false,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['workflow'] });
      void client.invalidateQueries({ queryKey: ['workflow-stats'] });
    },
  });
  const items = queue.data?.data || [];
  return (
    <div className="mx-auto max-w-6xl space-y-8 p-4 md:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">候选处理</h1>
          <p className="mt-2 max-w-2xl text-sm text-gray-600">
            先补齐范围，再准备标书。人工暂缓与拒绝会保留，审批和真实投标继续走原有流程。
          </p>
        </div>
        <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
          {sync.isPending ? '检查中…' : '检查已有项目与审批状态'}
        </Button>
      </div>
      {(queue.error || stats.error || sync.error) && (
        <p role="alert" className="text-sm text-red-700">
          {(queue.error || stats.error || sync.error)?.message}
        </p>
      )}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <label className="text-sm font-medium">
          候选状态
          <select
            className="ml-3 rounded-md border border-gray-300 px-3 py-2"
            value={state || ''}
            onChange={(e) => {
              setState((e.target.value as WorkflowState) || undefined);
              setOffset(0);
            }}
          >
            <option value="">全部</option>
            {Object.entries(labels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {queue.isPending && <p className="py-8 text-gray-500">正在读取候选…</p>}
        {!queue.isPending && items.length === 0 && (
          <p className="py-8 text-sm text-gray-600">
            当前没有此状态的候选。可检查已有项目；新增项目也会在抓取后进入队列。
          </p>
        )}
        {items.map((item) => (
          <Candidate key={`${item.project_id}:${item.revision}`} item={item} />
        ))}
        <div className="mt-4 flex items-center justify-between text-sm text-gray-600">
          <span>共 {queue.data?.total || 0} 个候选</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              disabled={offset + 50 >= (queue.data?.total || 0)}
              onClick={() => setOffset(offset + 50)}
            >
              下一页
            </Button>
          </div>
        </div>
      </section>
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">最近七天的流程记录</h2>
        <p className="text-sm text-gray-600">
          阶段计数记录实际处理条目或状态流转，同一项目可出现多次，不等于中标率。
        </p>
        {stats.data && (
          <p className="text-sm">
            评分模型调用 {stats.data.model_usage.calls} 次，缓存命中{' '}
            {stats.data.model_usage.cache_hits} 次。 已观察 token{' '}
            {stats.data.model_usage.observed_tokens}
            {stats.data.model_usage.token_usage_complete ? '' : '（部分调用缺少可用用量记录）'}
            。费用未核算。
          </p>
        )}
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white p-4">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="pb-3">阶段</th>
                  <th>结果 / 原因</th>
                  <th className="text-right">次数 / 条目</th>
                </tr>
              </thead>
              <tbody>
                {stats.data?.stages.map((item, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-3">{stageLabels[item.stage] || item.stage}</td>
                    <td>
                      {labels[item.outcome as WorkflowState] ||
                        resultLabels[item.outcome] ||
                        '已记录'}
                      {item.reason_code ? ` / ${reasonLabels[item.reason_code] || '需复核'}` : ''}
                    </td>
                    <td className="text-right">{item.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <p className="mb-3 text-sm font-medium">最近的运行</p>
            {stats.data?.runs.map((run) => (
              <div key={run.id} className="border-b py-3 text-sm last:border-0">
                <p>
                  {new Date(run.started_at).toLocaleString()}：
                  {run.status === 'completed'
                    ? '完成'
                    : run.status === 'failed'
                      ? '失败'
                      : run.status === 'completed_with_errors'
                        ? '完成，有部分失败'
                        : '运行中'}
                  {run.duration_ms !== null ? `，${(run.duration_ms / 1000).toFixed(1)} 秒` : ''}
                </p>
                {run.failed_stage && (
                  <p className="text-red-700">
                    失败阶段：{stageLabels[run.failed_stage] || run.failed_stage}
                  </p>
                )}
                {run.summary?.step_durations_ms && (
                  <p className="mt-1 text-xs text-gray-600">
                    {Object.entries(run.summary.step_durations_ms)
                      .map(
                        ([step, ms]) => `${stageLabels[step] || step} ${(ms / 1000).toFixed(1)} 秒`
                      )
                      .join('；')}
                  </p>
                )}
              </div>
            ))}
            {stats.data?.runs.length === 0 && (
              <p className="text-sm text-gray-600">暂无新版本运行记录。</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
