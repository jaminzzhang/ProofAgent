export type ReceiptOutcome =
  | 'ANSWERED_WITH_CITATIONS'
  | 'REFUSED_NO_EVIDENCE'
  | 'ESCALATED_WEAK_EVIDENCE'
  | 'WAITING_FOR_USER_CLARIFICATION'
  | 'WAITING_FOR_APPROVAL'
  | 'TOOL_APPROVAL_DENIED'
  | 'FAILED_WITH_TRACE'
  | 'FAILED_RECEIPT_UNAVAILABLE'

export interface GovernanceDetails {
  reasoning_summary?: Record<string, unknown> | null
  review_results?: Record<string, unknown>[]
  clarification_request?: Record<string, unknown> | null
}

export type ApprovalStatus = 'requested' | 'granted' | 'denied' | 'timed_out'

export interface RunSummary {
  run_id: string
  question: string
  outcome: ReceiptOutcome
  created_at: string
  updated_at: string
  approval_status: ApprovalStatus | null
  error_code: string | null
}

export interface RunDetail {
  run_id: string
  question: string
  outcome: ReceiptOutcome
  created_at: string
  updated_at: string
  approval_status: ApprovalStatus | null
  error_code: string | null
  trace_events: TraceEvent[]
  receipt_markdown: string
  evidence_chunks: EvidenceChunk[]
  policy_decisions: PolicyDecision[]
  model_usage: ModelUsage
  approval_state: ApprovalState | null
  governance_details?: GovernanceDetails
}

export interface TraceEvent {
  event_type: string
  event_id: string
  sequence: number
  timestamp: string
  status: 'ok' | 'blocked' | 'waiting' | 'error'
  payload: Record<string, unknown>
  run_id: string
}

export interface EvidenceChunk {
  index: number
  source: string
  score: number | null
  status: 'accepted' | 'rejected'
}

export interface PolicyDecision {
  event_id?: string
  timestamp?: string
  decision?: string
  policy_rule_id?: string
  reason?: string
}

export interface ModelUsage {
  provider?: string
  model?: string
  status?: string
  message_count?: number
  estimated_tokens?: number
  stream?: boolean
  cost_class?: string
  finish_reason?: string
  content_length?: number
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  error_code?: string
  error_class?: string
  retryable?: boolean
}

export interface ApprovalState {
  state: string
  tool_name?: string
  event_id?: string
  timestamp?: string
}

export interface StatsResponse {
  total_runs: number
  outcome_distribution: Record<string, number>
  pending_approvals: number
}

export interface RunsListResponse {
  data: RunSummary[]
  meta: {
    total: number
    limit: number
    offset: number
  }
}

export interface HealthResponse {
  status: string
  version: string
  history_dir: string
  total_runs: number
}

export interface ContextAdmission {
  admitted: boolean
  turn_count: number
  included_turn_ids: string[]
  summary: string
  char_count: number
  max_turns: number
}

export interface ConversationTurn {
  turn_id: string
  run_id: string
  agent_id: string
  question: string
  final_output: string
  outcome: ReceiptOutcome
  created_at: string
  context_admission: ContextAdmission
  evidence: any[]
  approval_state: ApprovalState | null
  governance_details?: GovernanceDetails
  links: {
    run_detail: string
    trace: string
    receipt: string
  }
}

export interface ConversationRecord {
  conversation_id: string
  agent_id: string
  created_at: string
  updated_at: string
  turns: ConversationTurn[]
}

export interface ChatRunResponse {
  agent_id: string
  run_id: string
  outcome: ReceiptOutcome
  final_output: string
  evidence: any[]
  approval_state: ApprovalState | null
  governance_details?: GovernanceDetails
  links: {
    run_detail: string
    trace: string
    receipt: string
  }
  conversation_id?: string
  turn_id?: string
  context_admission?: ContextAdmission
}
