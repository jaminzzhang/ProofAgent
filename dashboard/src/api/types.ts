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
  score?: number | null
  admission_score?: number | null
  provider_native_score?: number | null
  fusion_rank?: number | null
  source_id?: string | null
  binding_id?: string | null
  citation?: string | null
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
  display_name: string
  purpose: string
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

export interface KnowledgeSource {
  source_id: string
  name: string
  provider: string
  params: Record<string, unknown>
  created_at: string
  updated_at: string
  source_draft_version_id?: string | null
  latest_snapshot_id?: string | null
  published_snapshot_id?: string | null
  publication_count?: number
  document_count: number
  ready_document_count: number
}

export interface KnowledgeSourceSnapshotDocument {
  document_id: string
  revision_id: string
  filename: string
  content_type: string
  content_hash: string
  artifact_path: string
  routing_metadata: Record<string, unknown>
}

export interface CandidateKnowledgeSourceSnapshot {
  source_id: string
  source_draft_version_id: string
  candidate_digest: string
  included_documents: KnowledgeSourceSnapshotDocument[]
  queued_document_count: number
  processing_document_count: number
  failed_document_count: number
  archived_document_count: number
  required_reingestion_count: number
}

export interface KnowledgeSourceSnapshotManifest {
  schema_version: 'local_index.snapshot.v2'
  snapshot_id: string
  source_id: string
  state: 'READY'
  validation_level: 'foundation'
  source_draft_version_id: string
  candidate_digest: string
  foundation_validation_id: string
  documents: KnowledgeSourceSnapshotDocument[]
  created_at: string
  created_by: string
}

export interface KnowledgeSourcePublicationValidation {
  validation_id: string
  source_id: string
  snapshot_id: string
  source_draft_version_id: string
  candidate_digest: string
  status: 'passed'
  smoke_query: string
  candidate_count: number
  citation_count: number
  created_at: string
  created_by: string
}

export interface KnowledgeSourcePublicationRecord {
  publication_id: string
  source_id: string
  snapshot_id: string
  source_draft_version_id: string
  validation_id: string
  change_note: string
  published_at: string
  published_by: string
  document_count: number
  smoke_query: string
  smoke_result_summary: Record<string, unknown>
}

export interface KnowledgeDocument {
  document_id: string
  source_id: string
  revision_id: string
  filename: string
  content_type: string
  content_hash: string
  size_bytes: number
  state: 'queued' | 'processing' | 'ready' | 'failed' | string
  storage_path: string
  provider_document_id: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeSourcesResponse {
  data: KnowledgeSource[]
  meta: {
    total: number
  }
}

export interface KnowledgeDocumentsResponse {
  data: KnowledgeDocument[]
  meta: {
    total: number
  }
}

export interface KnowledgeSourcePublicationsResponse {
  data: KnowledgeSourcePublicationRecord[]
  meta: {
    total: number
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
