export interface ApiResponse<T> {
  status: string;
  data: T;
  total?: number;
  message?: string;
  is_syncing?: boolean;
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
