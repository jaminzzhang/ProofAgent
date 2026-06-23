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
export type WorkflowStageStatus = 'completed' | 'blocked' | 'waiting' | 'skipped'

export interface GovernanceDetails {
  intent_resolution?: Record<string, unknown> | null
  reasoning_summary?: Record<string, unknown> | null
  review_results?: Record<string, unknown>[]
  clarification_request?: Record<string, unknown> | null
}

export type ApprovalStatus = 'requested' | 'granted' | 'denied' | 'timed_out'

/** Approval Queue view filter (queue scoping), not the approval lifecycle. */
export type ApprovalStatusFilter = 'all' | 'pending' | 'expired'

export interface RunSummary {
  run_id: string
  question: string
  outcome: ReceiptOutcome
  run_purpose: RunPurpose
  agent_id: string | null
  agent_version_id: string | null
  draft_id: string | null
  validation_capture_id?: string | null
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
  validation_capture_id?: string | null
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
  pending_approvals: PendingApproval[]
  governance_details?: GovernanceDetails
  workflow_projection: WorkflowRunProjection
}

export interface WorkflowRunProjection {
  template_name: string | null
  template_descriptor_version: string | null
  stage_configuration_source: Record<string, unknown>
  stages: WorkflowRunStageProjection[]
}

export interface WorkflowRunStageProjection {
  stage_id: string
  visited: boolean
  label: string | null
  status: WorkflowStageStatus | string | null
  outcome: ReceiptOutcome | null
  safe_summary: Record<string, unknown>
  context_application_summary: Record<string, unknown>
  produced_fact_refs: string[]
  related_event_ids: string[]
  approval_pause_summary: Record<string, unknown> | null
  clarification_need_summary: Record<string, unknown> | null
}

export interface SensitiveValidationCaptureArtifactMetadata {
  capture_id: string
  run_id: string
  draft_id: string
  created_at: string
  expires_at: string
  created_by: string
  retention_class: 'sensitive_validation_capture'
  artifact_path: string
  retain_for_audit: boolean
  redaction_metadata: Record<string, unknown>
  exclusion_metadata: Record<string, unknown>
}

export interface ValidationCaptureSourceReference {
  run_id: string
  run_purpose: string
  agent_id: string | null
  agent_version_id: string | null
  draft_id: string | null
  validation_id: string | null
  template_name: string
  template_descriptor_version: string
  stage_configuration_source_type: string
  stage_configuration_source_reference: string | null
  effective_stage_configuration_ref: string | null
}

export interface WorkflowStagePromptValueCapture {
  stage_id: string
  stage_label?: string | null
  prompt_values: Record<string, unknown>
  prompt_field_names: string[]
  prompt_character_count: number
  redaction_applied: boolean
  source: string | null
}

export interface WorkflowStageContextConfigurationCapture {
  stage_id: string
  stage_label?: string | null
  selected_context_options: string[]
  available_context_options: string[]
}

export interface WorkflowStageContextApplicationProjection {
  stage_id: string
  stage_label?: string | null
  summary: Record<string, unknown>
}

export interface WorkflowStageResultVerificationProjection {
  stage_id: string
  stage_label?: string | null
  status: WorkflowStageStatus
  outcome: ReceiptOutcome | null
  summary: Record<string, unknown>
  produced_fact_refs: string[]
}

export interface WorkflowStageFailureDiagnosticProjection {
  stage_id: string
  stage_label?: string | null
  event_type: string
  status: WorkflowStageStatus
  error_code: string
  role?: string | null
  raw_content_length?: number | null
  related_event_id?: string | null
  contract_name?: string | null
  violation_codes?: string[]
  field_paths?: string[]
  violation_count?: number
}

export interface WorkflowStageLlmInteractionCapture {
  stage_id: string
  stage_label?: string | null
  role: string
  provider: string
  model: string
  request_json: Record<string, unknown>
  response_json: unknown | null
  response_content_length: number
  response_json_parse_error_code?: string | null
}

export interface ValidationCaptureResultSummary {
  outcome: ReceiptOutcome
  final_output: string
  final_output_length: number
  fact_refs: string[]
  approval_pause: Record<string, unknown> | null
  clarification_need: Record<string, unknown> | null
}

export interface ValidationCaptureExclusionSummary {
  excluded_categories: string[]
  sanitizer_version: string
  redacted_secret_count: number
  dropped_unsafe_key_count: number
  redaction_applied: boolean
}

export interface ValidationCaptureV2Payload {
  capture_contract_version: 'validation_capture.v2'
  source: ValidationCaptureSourceReference
  stage_prompt_values: WorkflowStagePromptValueCapture[]
  context_configuration: WorkflowStageContextConfigurationCapture[]
  context_applications: WorkflowStageContextApplicationProjection[]
  stage_results: WorkflowStageResultVerificationProjection[]
  failure_diagnostics?: WorkflowStageFailureDiagnosticProjection[]
  llm_interactions?: WorkflowStageLlmInteractionCapture[]
  result_summary: ValidationCaptureResultSummary
  exclusions: ValidationCaptureExclusionSummary
}

export interface ValidationCaptureResponse {
  metadata: SensitiveValidationCaptureArtifactMetadata
  payload: ValidationCaptureV2Payload
}

export interface TraceEvent {
  schema_version?: string
  event_type: string
  event_id: string
  sequence: number
  timestamp: string
  status: 'ok' | 'blocked' | 'waiting' | 'error'
  payload: Record<string, unknown>
  run_id: string
  span_id?: string
  parent_span_id?: string | null
  redaction?: Record<string, unknown>
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
  approval_id?: string
  event_id?: string
  timestamp?: string
}

export interface PendingApproval {
  run_id: string
  thread_id: string
  approval_id: string
  action_id: string
  tool_name: string
  parameters: Record<string, unknown>
  policy_decision: unknown
  checkpoint_id: string
  status: string
  created_at: string
  expires_at: string
}

export interface ApprovalQueueItem {
  run_id: string
  approval_id: string
  tool_name: string
  action_id: string
  question: string
  agent_id: string | null
  agent_version_id: string | null
  run_purpose: RunPurpose
  created_at: string
  expires_at: string
  expired: boolean
  parameter_keys: string[]
  parameter_count: number
  links: {
    run_detail: string
  }
}

export interface ApprovalsResponse {
  data: ApprovalQueueItem[]
  meta: {
    total: number
    limit: number
    offset: number
  }
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

export type EvaluationCampaignReadinessStatus = 'ready' | 'blocked'
export type EvaluationCampaignCapabilityStatus = 'passed' | 'failed' | 'not_covered'

export interface EvaluationCampaignSuiteRun {
  source: string
  suite_id: string
  suite_version: string
  analysis_id: string
  release_decision_status: 'passed' | 'blocked'
  total_required_cases: number
  passed_required_cases: number
  governed_resolution_rate: number
  artifact_dir: string
}

export interface EvaluationCampaignCapabilityCoverage {
  capability_path: string
  status: EvaluationCampaignCapabilityStatus
  required_cases: number
  passed_required_cases: number
  failed_required_cases: number
}

export interface EvaluationDiagnosticFinding {
  severity: 'low' | 'medium' | 'high'
  category: string
  summary: string
}

export interface EvaluationCaseDiagnostic {
  case_id: string
  status: 'passed_with_diagnostics' | 'needs_review'
  quality_score: number
  findings: EvaluationDiagnosticFinding[]
  diagnostic_blocker_candidate: boolean
}

export interface EvaluationCampaignDiagnostics {
  diagnostics_version: string
  evaluated_case_count: number
  mean_quality_score: number | null
  diagnostic_blocker_candidate_count: number
  case_diagnostics: EvaluationCaseDiagnostic[]
}

export interface EvaluationCampaignCaseResponseProjection {
  audience?: string
  ref?: string
  declared_sha256?: string
  observed_text_sha256?: string
  text_length?: number
  source?: string
  sensitivity?: string
}

export interface EvaluationCampaignCaseGateFailure {
  gate: string
  status: string
  reason: string
  failure_owner: string | null
}

export interface EvaluationCampaignCaseRow {
  analysis_id: string
  source?: string
  suite_id: string
  suite_version: string
  case_id: string
  scenario_id?: string | null
  scenario_step_id?: string | null
  status: string
  expected_outcome: string
  actual_outcome: string | null
  artifact_sufficiency: string | null
  primary_failure_owner: string | null
  response_projection: EvaluationCampaignCaseResponseProjection | null
  gate_failures: EvaluationCampaignCaseGateFailure[]
  diagnostic_findings: EvaluationDiagnosticFinding[]
  diagnostic_blocker_candidate: boolean
}

export interface EvaluationCampaignCasesResponse {
  campaign_id: string
  data: EvaluationCampaignCaseRow[]
  meta: {
    total: number
  }
}

export type EvaluationCampaignTrendStatus =
  | 'comparable'
  | 'benchmark_migration'
  | 'no_baseline'

export interface EvaluationCampaignTrendSuiteVersion {
  source: string
  suite_id: string
  current_suite_version?: string | null
  baseline_suite_version?: string | null
  comparable: boolean
}

export interface EvaluationCampaignTrendBasis {
  target_agent_id?: string | null
  current_target_agent_version_id?: string | null
  baseline_target_agent_version_id?: string | null
  suite_versions: EvaluationCampaignTrendSuiteVersion[]
}

export interface EvaluationCampaignTrend {
  campaign_id: string
  current_version: string
  baseline_campaign_id: string | null
  baseline_version: string | null
  status: EvaluationCampaignTrendStatus
  comparison_basis: EvaluationCampaignTrendBasis
  metric_deltas: {
    governed_resolution_rate?: number
    artifact_sufficiency_rate?: number
    deterministic_gate_pass_rate?: number
  }
}

export interface EvaluationCampaignSummary {
  campaign_id: string
  version: string
  target_agent_id: string
  target_agent_version_id: string | null
  readiness_status: EvaluationCampaignReadinessStatus
  blocking_reasons: string[]
  governed_resolution_rate: number
  artifact_sufficiency_rate: number
  deterministic_gate_pass_rate: number
  suite_runs: EvaluationCampaignSuiteRun[]
  capability_coverage: EvaluationCampaignCapabilityCoverage[]
  coding_agent_diagnostics?: EvaluationCampaignDiagnostics | null
  artifact_dir: string
}

export interface EvaluationCampaignsResponse {
  data: EvaluationCampaignSummary[]
  meta: {
    total: number
  }
}

export interface EvaluationProductionSampleSafeSummary {
  question_sha256?: string
  question_text_length?: number
  response_text_sha256?: string
  response_text_length?: number
}

export interface EvaluationProductionSampleCandidate {
  batch_id: string
  batch_dir: string
  sample_id: string
  source_run_id?: string
  curation_status: string
  formal_scoring_allowed: boolean
  run_purpose?: string
  safe_summary?: EvaluationProductionSampleSafeSummary
}

export interface EvaluationProductionSampleCandidatesResponse {
  data: EvaluationProductionSampleCandidate[]
  meta: {
    total: number
  }
}

export interface EvaluationProductionSampleReviewer {
  reviewer: string
  confirmed: boolean
  notes?: string | null
}

export interface EvaluationProductionSamplePromotion {
  promotion_dir: string
  promotion_record_path: string
  sample_id: string
  status: string
  source_run_id?: string
  suite_path?: string
  subject_manifest_path?: string
  domain_review?: EvaluationProductionSampleReviewer
  harness_review?: EvaluationProductionSampleReviewer
}

export interface EvaluationProductionSamplePromotionsResponse {
  data: EvaluationProductionSamplePromotion[]
  meta: {
    total: number
  }
}

export interface EvaluationProductionSamplePromotionCaseRequest {
  case_id: string
  question: string
  intent_type: string
  expected_resolution: string
  risk_class: string
  capability_path: string
  expected_outcome: ReceiptOutcome
  required_citation_refs: string[]
}

export interface EvaluationProductionSamplePromotionRequest {
  batch_id: string
  sample_id: string
  suite_id: string
  suite_version: string
  manifest_id: string
  case: EvaluationProductionSamplePromotionCaseRequest
  domain_review: EvaluationProductionSampleReviewer
  harness_review: EvaluationProductionSampleReviewer
}

export interface ContractBundle {
  agent_yaml: string
  policy_yaml: string
  tools_yaml: string
  extra_files: Record<string, string>
  advanced_fields: Record<string, unknown>
}

export interface WorkflowStageDescriptor {
  id: string
  label: string
  description: string
  predecessors: string[]
  successors: string[]
  branch_conditions: Record<string, string>
  governed_handoff_points: string[]
  editable_prompt_fields: string[]
  context_options: string[]
  input_summary: string
  output_summary: string
  model_bearing: boolean
  required: boolean
}

export interface WorkflowTemplateDescriptor {
  name: string
  description: string
  descriptor_version: string
  stages: WorkflowStageDescriptor[]
}

export interface WorkflowTemplatesResponse {
  data: WorkflowTemplateDescriptor[]
  meta: {
    total: number
  }
}

export interface WorkflowStagePromptConfig {
  business_context?: string | null
  task_instructions: string[]
  output_preferences: string[]
}

export interface WorkflowStageConfig {
  id: string
  prompt: WorkflowStagePromptConfig
  context: Record<string, boolean>
}

export interface WorkflowStageContextPreview {
  stage_id: string
  stage_label: string
  harness_control_prompt_summary: string
  structured_control_context: Record<string, unknown>
  business_context_addendum: {
    present: boolean
    text: string
    fields: string[]
  }
  summary: Record<string, unknown>
}

export interface BusinessFlowSkillAddendumSlot {
  stage_id: string
  stage_label: string
}

export interface BusinessFlowSkillPackPromptPreview {
  merge_mode: 'append'
  business_context: string
  task_instructions: string[]
  output_preferences: string[]
}

export interface BusinessFlowSkillPackStageAddendum {
  stage_id: string
  stage_label: string
  configured: boolean
  prompt: WorkflowStagePromptConfig
  preview: BusinessFlowSkillPackPromptPreview
}

export interface BusinessFlowSkillPackRoutingAdmission {
  intent_patterns: string[]
  intent_taxonomy_refs: string[]
  admission: Record<string, unknown>
  routing_safe_summary: Record<string, unknown>
}

export interface BusinessFlowSkillPackCapabilityRefs {
  knowledge_binding_refs: string[]
  tool_contract_refs: string[]
  policy_rule_refs: string[]
  validator_refs: string[]
}

export interface BusinessFlowSkillPackProjection {
  id: string
  label: string
  description: string
  definition: string
  default: boolean
  routing_admission: BusinessFlowSkillPackRoutingAdmission
  capability_refs: BusinessFlowSkillPackCapabilityRefs
  stage_addenda: BusinessFlowSkillPackStageAddendum[]
  coverage: {
    configured_stage_ids: string[]
    missing_stage_ids: string[]
  }
}

export interface BusinessFlowSkillPackConfiguration {
  enabled: boolean
  template_name: string
  template_descriptor_version: string
  addendum_slots: BusinessFlowSkillAddendumSlot[]
  packs: BusinessFlowSkillPackProjection[]
}

export interface BusinessFlowSkillPackCreateRequest {
  id: string
  label: string
  description: string
  intent_patterns?: string[]
  intent_taxonomy_refs?: string[]
  default?: boolean
}

export interface BusinessFlowSkillPackUpdateRequest {
  label?: string | null
  description?: string | null
  intent_patterns?: string[] | null
  intent_taxonomy_refs?: string[] | null
  stage_prompt_addenda?: Record<string, WorkflowStagePromptConfig> | null
  knowledge_binding_refs?: string[] | null
  tool_contract_refs?: string[] | null
  policy_rule_refs?: string[] | null
  validator_refs?: string[] | null
  admission?: Record<string, unknown> | null
  default?: boolean | null
}

export type ConfigurationOperation =
  | 'created'
  | 'imported'
  | 'updated'
  | 'validated'
  | 'published'
  | 'rolled_back'
  | 'archived'
  | 'restored'
  | 'physical_deleted'

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
  validation_capture_id?: string | null
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

export type SharedModelConnectionLifecycleState = 'ACTIVE' | 'ARCHIVED'

export interface EnvironmentModelCredentialReference {
  type: 'env'
  name: string
}

export interface SharedModelConnectionReferenceSummary {
  connection_id: string
  draft_agent_reference_count: number
  published_agent_version_reference_count: number
  knowledge_source_reference_count: number
  in_flight_operation_count: number
  audit_retention_blocked: boolean
}

export interface ModelConnectionImpactReviewDetail {
  requires_impact_review: true
  changed_fields: string[]
  reference_summary: SharedModelConnectionReferenceSummary
}

export interface ModelConnectionValidationRecord {
  validation_id: string
  connection_id: string
  status: 'passed' | 'failed'
  created_at: string
  created_by: string
  provider: string
  model_identifier: string
  credential_ref: EnvironmentModelCredentialReference
  checked_env_vars: string[]
  missing_env_vars: string[]
  error_code: string | null
  message: string
}

export interface ModelConnectionSmokeTestRecord {
  smoke_test_id: string
  connection_id: string
  status: 'passed' | 'failed' | 'skipped'
  created_at: string
  created_by: string
  provider: string
  model_identifier: string
  credential_ref: EnvironmentModelCredentialReference
  request_sent: boolean
  error_code: string | null
  message: string
}

export interface SharedModelConnection {
  connection_id: string
  display_name: string
  description: string
  tags: string[]
  provider: string
  model_identifier: string
  base_url: string | null
  credential_ref: EnvironmentModelCredentialReference
  organization_env: string | null
  project_env: string | null
  timeout_seconds: number | null
  lifecycle_state: SharedModelConnectionLifecycleState
  created_at: string
  updated_at: string
  reference_summary: SharedModelConnectionReferenceSummary
  last_validation: ModelConnectionValidationRecord | null
  last_smoke_test: ModelConnectionSmokeTestRecord | null
}

export interface SharedModelConnectionDeletionEligibility {
  connection_id: string
  eligible: boolean
  lifecycle_state: SharedModelConnectionLifecycleState
  reference_summary: SharedModelConnectionReferenceSummary
  blockers: string[]
}

export interface ModelConnectionsResponse {
  data: SharedModelConnection[]
  meta: {
    total: number
  }
}

export interface KnowledgeSource {
  source_id: string
  name: string
  provider: string
  lifecycle_state: KnowledgeSourceLifecycleState
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

export type KnowledgeSourceLifecycleState = 'ACTIVE' | 'ARCHIVED'

export interface KnowledgeSourceReferenceSummary {
  source_id: string
  draft_agent_binding_count: number
  published_agent_version_count: number
  publication_count: number
  snapshot_count: number
  document_count: number
  quarantined_upload_count: number
  ingestion_job_count: number
  audit_retention_blocked: boolean
}

export interface KnowledgeSourceDeletionEligibility {
  source_id: string
  eligible: boolean
  lifecycle_state: KnowledgeSourceLifecycleState
  reference_summary: KnowledgeSourceReferenceSummary
  blockers: string[]
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

export interface FoundationKnowledgeSourceValidation {
  validation_id: string
  source_id: string
  source_draft_version_id: string
  candidate_digest: string
  validation_level: 'foundation'
  status: 'passed'
  document_count: number
  required_reingestion_count: number
  created_at: string
  created_by: string
}

export interface KnowledgeSourcePublicationValidation {
  validation_id: string
  source_id: string
  resource_kind?: 'local_index_snapshot' | 'remote_config'
  resource_id?: string | null
  snapshot_id: string | null
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
  resource_kind?: 'local_index_snapshot' | 'remote_config'
  resource_id?: string | null
  snapshot_id: string | null
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
  routing_metadata: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface QuarantinedKnowledgeUpload {
  upload_id: string
  source_id: string
  filename: string
  content_type: string
  size_bytes: number
  storage_path: string
  state: string
  attempt_count?: number
  claimed_at?: string | null
  claim_token?: string | null
  lease_expires_at?: string | null
  completed_at?: string | null
  error_code?: string | null
  error_message?: string | null
  promoted_document_id?: string | null
  promoted_revision_id?: string | null
  ingestion_job_id?: string | null
  expires_at?: string | null
  purged_at?: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeIngestionJob {
  job_id: string
  source_id: string
  document_id: string
  revision_id: string
  state: string
  attempt_count: number
  auto_retry_count: number
  max_auto_retries: number
  ingestion_config_fingerprint: string
  artifact_build_spec: Record<string, unknown>
  artifact_path?: string | null
  claimed_at?: string | null
  claim_token?: string | null
  lease_expires_at?: string | null
  completed_at?: string | null
  error_code?: string | null
  error_message?: string | null
  last_error_code?: string | null
  last_error_message?: string | null
  last_failure_classification?: string | null
  next_attempt_at?: string | null
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

export interface KnowledgeUploadsResponse {
  data: QuarantinedKnowledgeUpload[]
  meta: {
    total: number
  }
}

export interface KnowledgeIngestionJobsResponse {
  data: KnowledgeIngestionJob[]
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
  warnings?: Record<string, unknown>[]
  publish_blockers?: Record<string, unknown>[]
  trace_capture?: {
    mode: 'summary_only' | 'full_capture'
    validation_capture: SensitiveValidationCaptureArtifactMetadata | null
    capture_error?: {
      code: string
      message: string
      retryable: boolean
    }
  }
  links: {
    run_detail: string
    trace: string
    receipt: string
    validation_capture?: string
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
