import type {
  ApiResponse,
  Project,
  ProjectFilters,
  Stats,
  ScoringRule,
  PromptTemplate,
  Proposal,
  ProposalStats,
  CompetitorAnalysis,
  Message,
  MessageThread,
  BidApproval,
  WorkflowCandidate,
  WorkflowStats,
  WorkflowState,
} from './types';

export function getWorkflow(state?: WorkflowState, offset = 0) {
  const params = new URLSearchParams({ limit: '50', offset: String(offset) });
  if (state) params.set('state', state);
  return request<ApiResponse<WorkflowCandidate[]>>(`/workflow?${params}`);
}

export async function getWorkflowStats() {
  return (await request<ApiResponse<WorkflowStats>>('/workflow/stats')).data;
}

export function syncWorkflow() {
  return request('/workflow/sync', json('POST', { since_days: 7, threshold: 7 }));
}

export function decideWorkflow(
  projectId: number,
  revision: number,
  action: 'defer' | 'reject' | 'resume',
  reason: string,
  resumeAt?: string
) {
  return request<ApiResponse<WorkflowCandidate>>(
    `/workflow/${projectId}/decision`,
    json('POST', { revision, action, reason, ...(resumeAt ? { resume_at: resumeAt } : {}) })
  );
}

export function resolveWorkflow(
  projectId: number,
  revision: number,
  answers: { id: string; answer: string }[]
) {
  return request<ApiResponse<WorkflowCandidate>>(
    `/workflow/${projectId}/clarifications`,
    json('POST', { revision, answers })
  );
}

function configuration() {
  return {
    base:
      (typeof window !== 'undefined' && localStorage.getItem('api_url')) ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://localhost:8000/api/v1',
    key: typeof window !== 'undefined' ? localStorage.getItem('api_key') || '' : '',
  };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { base, key } = configuration();
  const response = await fetch(`${base.replace(/\/$/, '')}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': key,
      ...options.headers,
    },
    signal: options.signal || AbortSignal.timeout(120000),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof body.detail === 'string' ? body.detail : `请求失败 (${response.status})`
    );
  }
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export async function searchProjects(filters: ProjectFilters = {}) {
  if (filters.country || filters.skills?.some((skill) => !/^\d+$/.test(skill))) {
    throw new Error('当前接口仅支持数字技能 ID，暂不支持国家筛选。');
  }
  const params = new URLSearchParams();
  const values = {
    query: filters.query,
    status: filters.status,
    skills: filters.skills?.join(','),
    score_min: filters.score_range?.[0] ?? filters.min_score,
    score_max: filters.score_range?.[1],
    budget_min: filters.budget_min,
    budget_max: filters.budget_max,
    refresh: filters.refresh,
    limit: filters.limit,
    offset: filters.offset,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') params.set(key, String(value));
  }
  return request<ApiResponse<Project[]>>(`/projects/search?${params}`);
}

export async function getProject(id: number) {
  return (await request<ApiResponse<Project>>(`/projects/${id}`)).data;
}
export async function getStats() {
  return (await request<ApiResponse<Stats>>('/stats')).data;
}
export async function scoreProject(id: number) {
  return (await request<ApiResponse<Project>>(`/projects/${id}/score`, json('POST'))).data;
}
export async function batchScoreProjects(ids: number[]) {
  const results: Project[] = [];
  for (const id of ids) results.push(await scoreProject(id));
  return results;
}

export async function createBid(
  projectId: number,
  data: {
    amount: number;
    period: number;
    description?: string;
    amount_currency?: string;
    approval_id?: string;
  }
) {
  return request<ApiResponse<{ bid_id: number; status: string }>>(
    '/bids',
    json('POST', { project_id: projectId, ...data })
  );
}

export async function prepareBid(
  projectId: number,
  amount: number,
  period: number,
  currency: string
) {
  return (
    await request<ApiResponse<BidApproval>>(
      '/approvals/prepare',
      json('POST', { project_id: projectId, amount, period, amount_currency: currency })
    )
  ).data;
}

export async function getBidApproval(id: string) {
  return (await request<ApiResponse<BidApproval>>(`/approvals/${encodeURIComponent(id)}`)).data;
}

function unsupported(operation: string): never {
  throw new Error(`${operation}尚未接入，请使用现有 Python 流水线。`);
}
export async function flagProject(_id: number, _flag: boolean): Promise<void> {
  unsupported('项目标记');
}
export async function archiveProject(_id: number, _archive: boolean): Promise<void> {
  unsupported('项目归档');
}
export async function getCompetitorAnalysis(_id: number): Promise<CompetitorAnalysis[]> {
  unsupported('竞争者分析');
}
export async function triggerScript(name: string) {
  if (name === 'refresh_projects') return searchProjects({ refresh: true });
  unsupported('后台批量评分');
}

export async function exportProjects(options: {
  format: 'csv' | 'xlsx' | 'json';
  fields: string[];
  filters: ProjectFilters;
}) {
  if (options.format === 'xlsx') unsupported('Excel 导出');
  const projects: Project[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await searchProjects({ ...options.filters, refresh: false, limit: 100, offset });
    projects.push(...page.data);
    if (page.data.length < 100) break;
  }
  if (options.format === 'json') {
    return new Blob([JSON.stringify(projects, null, 2)], { type: 'application/json' });
  }
  const quote = (value: unknown) => {
    let text = String(value ?? '');
    if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const fields = options.fields as (keyof Project)[];
  const rows = [fields.join(','), ...projects.map((p) => fields.map((f) => quote(p[f])).join(','))];
  return new Blob(['\uFEFF', rows.join('\r\n')], { type: 'text/csv;charset=utf-8' });
}

export async function checkHealth(): Promise<{
  status: string;
  version?: string;
  service?: string;
} | null> {
  try {
    const { base } = configuration();
    const url = new URL(base);
    url.pathname = '/health';
    url.search = '';
    const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export async function getScoringRules() {
  return (await request<ApiResponse<ScoringRule[]>>('/scoring-rules')).data;
}
export async function updateScoringRule(id: number, data: Partial<ScoringRule>) {
  return (await request<ApiResponse<ScoringRule>>(`/scoring-rules/${id}`, json('PUT', data))).data;
}
export async function getPromptTemplates(category?: string) {
  const query = category ? `?category=${encodeURIComponent(category)}` : '';
  return (await request<ApiResponse<PromptTemplate[]>>(`/prompt-templates${query}`)).data;
}
export async function createPromptTemplate(data: Omit<PromptTemplate, 'id' | 'created_at'>) {
  return (await request<ApiResponse<PromptTemplate>>('/prompt-templates', json('POST', data))).data;
}
export async function updatePromptTemplate(id: number, data: Partial<PromptTemplate>) {
  return (await request<ApiResponse<PromptTemplate>>(`/prompt-templates/${id}`, json('PUT', data)))
    .data;
}
export async function deletePromptTemplate(id: number) {
  return request(`/prompt-templates/${id}`, json('DELETE'));
}
export const getProposalTemplates = () => getPromptTemplates('proposal');
export const createProposalTemplate = createPromptTemplate;
export const updateProposalTemplate = updatePromptTemplate;
export const deleteProposalTemplate = deletePromptTemplate;

export async function getProposals() {
  return (await request<ApiResponse<Proposal[]>>('/proposals')).data;
}
export async function getProposalStats() {
  return (await request<ApiResponse<ProposalStats>>('/proposals/stats')).data;
}

export async function getMessageThreads(): Promise<MessageThread[]> {
  const result = await request<
    ApiResponse<
      {
        thread_id: number;
        project_id: number;
        unread_count: number;
        last_message_time?: string;
        last_message_preview?: string;
      }[]
    >
  >('/messages/threads');
  return result.data.map((t) => ({
    thread_id: t.thread_id,
    project_id: t.project_id,
    project_title: `项目 ${t.project_id ?? ''}`,
    unread_count: t.unread_count,
    messages: [],
    last_message: t.last_message_preview
      ? {
          content: t.last_message_preview,
          sender_name: '',
          created_at: t.last_message_time || '',
        }
      : undefined,
  }));
}
export async function getMessages(threadId: number): Promise<Message[]> {
  const result = await request<
    ApiResponse<
      {
        id: number;
        thread_id: number;
        user_id: number;
        username?: string;
        message: string;
        is_read: boolean;
        send_time?: string;
        created_at: string;
      }[]
    >
  >(`/messages/${threadId}`);
  return result.data.map((m) => ({
    id: m.id,
    thread_id: m.thread_id,
    sender_id: m.user_id,
    sender_name: m.username || String(m.user_id),
    content: m.message,
    is_read: m.is_read,
    created_at: m.send_time || m.created_at,
  }));
}
export async function sendMessage(threadId: number, content: string, _messageType?: string) {
  return request('/messages', json('POST', { thread_id: threadId, message: content }));
}
export async function markMessageAsRead(_messageId: number): Promise<void> {
  unsupported('单条消息已读');
}
export async function markThreadAsRead(threadId: number) {
  return request(`/messages/${threadId}/read`, json('PUT'));
}
export async function getUnreadCount() {
  return (await getMessageThreads()).reduce((count, thread) => count + thread.unread_count, 0);
}
