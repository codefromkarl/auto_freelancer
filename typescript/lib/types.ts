export interface ApiResponse<T> {
  status: string;
  data: T;
  total?: number;
  message?: string;
  is_syncing?: boolean;
}

export interface BidApproval {
  id: string;
  digest: string;
  state: string;
  expires_at: number;
  submission_enabled: boolean;
  payload: {
    project_id: number;
    title: string;
    amount: number;
    currency: string;
    period: number;
    description: string;
    review_required: boolean;
    review_notes: string[];
    authorization?: { mode: 'automatic'; source: 'automatic_policy'; version: string };
    competition_review?: {
      status: string;
      policy_version: string;
      premium_pct: number | null;
      findings: string[];
      blocking_issues: string[];
      benchmark: {
        status: string;
        currency: string;
        visible_count: number;
        price_count: number;
        complete: boolean;
        price: { median?: number };
      };
    };
  };
}

export type WorkflowState =
  | 'needs_evaluation'
  | 'needs_clarification'
  | 'ready'
  | 'awaiting_approval'
  | 'awaiting_submission'
  | 'deferred'
  | 'rejected'
  | 'submitted'
  | 'outcome_unknown';

export interface WorkflowCandidate {
  project_id: number;
  title: string;
  state: WorkflowState;
  reason_code: string;
  reason: string;
  revision: number;
  questions: { id: string; question: string }[];
  answers: { id: string; question: string; answer: string; source: string }[];
  held_by: string | null;
  resume_condition: string | null;
  resume_at: string | null;
  approval_id: string | null;
  ai_score: number | null;
  updated_at: string | null;
}

export interface BidOutcomeObservation {
  project_id: number;
  title: string;
  bid_id: number;
  amount: number;
  currency: string;
  days: number;
  state: 'active' | 'awarded' | 'withdrawn' | 'inactive' | 'unknown';
  reason: string | null;
  checked_at: string | null;
  customer_response: {
    state: 'observed' | 'none_observed' | 'unknown';
    reason?: string | null;
    previously_observed_at?: string;
  };
}

export interface WorkflowStats {
  bid_outcomes?: {
    counts: {
      submitted: number;
      active: number;
      awarded: number;
      withdrawn: number;
      inactive: number;
      unknown: number;
      responses: number;
    };
    rows: BidOutcomeObservation[];
  };
  queue: Partial<Record<WorkflowState, number>>;
  stages: { stage: string; outcome: string; reason_code: string | null; count: number }[];
  model_usage: {
    calls: number;
    cache_hits: number;
    assessment_reuses?: number;
    observed_tokens: number;
    token_usage_complete: boolean;
    cost: null;
  };
  runs: {
    id: string;
    status: string;
    started_at: string;
    duration_ms: number | null;
    failed_stage: string | null;
    summary: { step_durations_ms?: Record<string, number> } | null;
  }[];
}

export interface Project {
  id: number;
  title: string;
  description?: string | null;
  full_description?: string | null;
  preview_description?: string | null;
  budget_minimum?: number | null;
  budget_maximum?: number | null;
  currency_code: string;
  submitdate?: string | null;
  status: string;
  skills?: string | null;
  country?: string | null;
  owner_id?: number | null;
  owner_info?: Record<string, unknown> | string | null;
  ai_score?: number | null;
  ai_reason?: string | null;
  scored_at?: string | null;
  score_metadata?: {
    source: 'llm' | 'manual' | 'rule';
    version?: string;
    total: number;
    dimensions?: Record<string, number>;
    net_hourly_usd?: number;
    unknown?: string[];
  } | null;
  ai_proposal_draft?: string | null;
  suggested_bid?: number | null;
  estimated_hours?: number | null;
  hourly_rate?: number | null;
  deadline?: string | null;
  created_at?: string;
}

export interface ProjectFilters {
  query?: string;
  status?: string;
  min_score?: number;
  score_range?: [number, number];
  skills?: string[];
  country?: string;
  budget_min?: number;
  budget_max?: number;
  refresh?: boolean;
  limit?: number;
  offset?: number;
}

export interface Stats {
  total_projects: number;
  today_new: number;
  avg_score: number;
  pending_bids: number;
  score_distribution?: { range: string; count: number }[];
  budget_distribution?: { name: string; value: number }[];
}

export interface ScoringRule {
  id: number;
  name: string;
  description?: string | null;
  weight: number;
  is_active: boolean;
}

export interface PromptTemplate {
  id: number;
  name: string;
  category: string;
  content: string;
  variables: string[];
  is_active: boolean;
  created_at?: string;
}
export type ProposalTemplate = PromptTemplate;

export interface Proposal {
  id: number;
  project_id: number;
  project_title: string;
  project_budget: string;
  amount: number;
  period: number;
  description: string;
  status: string;
  submitdate?: string | null;
  ai_score?: number | null;
  competitor_count?: number;
  win_probability?: number;
}

export interface ProposalStats {
  total: number;
  accepted: number;
  rejected: number;
  pending: number;
  success_rate: number;
  avg_amount: number;
}

export interface CompetitorAnalysis {
  bidder_id: number;
  bidder_name: string;
  amount: number;
  period: number;
  rating: number;
  bid_count: number;
  success_rate: number;
}

export interface Message {
  id: number;
  thread_id?: number;
  project_id?: number;
  project_title?: string;
  sender_id?: number;
  receiver_id?: number;
  sender_name: string;
  sender_avatar?: string;
  content: string;
  is_read: boolean;
  created_at: string;
  ai_suggestions?: string[];
  message_type?: string;
}

export interface MessageThread {
  thread_id: number;
  project_id: number;
  project_title: string;
  unread_count: number;
  last_message?: Pick<Message, 'content' | 'sender_name' | 'created_at'>;
  messages: Message[];
}
