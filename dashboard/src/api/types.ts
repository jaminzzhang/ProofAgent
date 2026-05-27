export type ReceiptOutcome =
  | 'ANSWERED_WITH_CITATIONS'
  | 'REFUSED_NO_EVIDENCE'
  | 'ESCALATED_WEAK_EVIDENCE'
  | 'WAITING_FOR_USER_CLARIFICATION'
  | 'WAITING_FOR_APPROVAL'
  | 'TOOL_APPROVAL_DENIED'
  | 'FAILED_WITH_TRACE'
  | 'FAILED_RECEIPT_UNAVAILABLE'

export type RunPurpose = 'production' | 'validation'
export type RunPurposeFilter = RunPurpose | 'all'

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
  run_purpose: RunPurpose
  agent_id: string | null
  agent_version_id: string | null
  draft_id: string | null
  created_at: string
  updated_at: string
  approval_status: ApprovalStatus | null
  error_code: string | null
}

export interface RunDetail {
  run_id: string
  question: string
  outcome: ReceiptOutcome
  run_purpose: RunPurpose
  agent_id: string | null
  agent_version_id: string | null
  draft_id: string | null
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

export interface HandoffProjection {
  handoff_id: string
  run_id: string
  conversation_id: string
  turn_id: string
  reason: string
  question_summary: string
  summary: string
  created_at: string
  customer_ref: string | null
  status: string
}

export interface HandoffsResponse {
  data: HandoffProjection[]
}

export interface ContractBundle {
  agent_yaml: string
  policy_yaml: string
  tools_yaml: string
  extra_files: Record<string, string>
  advanced_fields: Record<string, unknown>
}

export type ConfigurationOperation =
  | 'imported'
  | 'updated'
  | 'validated'
  | 'published'
  | 'rolled_back'

export interface ConfigurationOperationAudit {
  operation_id: string
  operation: ConfigurationOperation
  actor: string
  created_at: string
  summary: string
  metadata: Record<string, unknown>
}

export interface AgentValidationRecord {
  validation_id: string
  draft_id: string
  run_id: string
  status: string
  created_at: string
  summary: string
  errors: string[]
}

export interface ConfigAgentSummary {
  agent_id: string
  display_name: string
  purpose: string
  draft_count: number
  latest_draft_id: string | null
  version_count: number
  active_version_id: string | null
  updated_at: string | null
}

export interface DraftAgent {
  agent_id: string
  draft_id: string
  display_name: string
  purpose: string
  created_at: string
  updated_at: string
  created_by: string
  updated_by: string
  version_id: string | null
  validation_records: AgentValidationRecord[]
  operation_audit: ConfigurationOperationAudit[]
}

export interface PublishedAgentVersion {
  agent_id: string
  version_id: string
  source_draft_id: string
  validation_run_id: string
  published_at: string
  published_by: string
  operation_audit: ConfigurationOperationAudit[]
}

export interface ActiveAgentVersion {
  agent_id: string
  version_id: string
  activated_at: string
  activated_by: string
  rollback_from_version_id: string | null
}

export interface ConfigAgentsResponse {
  data: ConfigAgentSummary[]
  meta: {
    total: number
  }
}

export interface ConfigVersionsResponse {
  data: PublishedAgentVersion[]
  meta: {
    total: number
    active_version_id: string | null
  }
}

export interface DraftValidationResponse {
  validation_id: string
  run_id: string
  status: string
  outcome: ReceiptOutcome
  run_purpose: RunPurpose
  agent_id: string
  draft_id: string
  links: {
    run_detail: string
    trace: string
    receipt: string
  }
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
  agent_version_id: string | null
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
