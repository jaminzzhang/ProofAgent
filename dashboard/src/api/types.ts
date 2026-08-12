export type ReceiptOutcome =
  | 'ANSWERED_WITH_CITATIONS'
  | 'REFUSED_NO_EVIDENCE'
  | 'ESCALATED_WEAK_EVIDENCE'
  | 'WAITING_FOR_USER_CLARIFICATION'
  | 'WAITING_FOR_APPROVAL'
  | 'TOOL_APPROVAL_DENIED'
  | 'POLICY_DENIED'
  | 'FAILED_WITH_TRACE'
  | 'FAILED_RECEIPT_UNAVAILABLE'

export type RunPurpose = 'production' | 'validation'
export type RunPurposeFilter = RunPurpose | 'all'
export type WorkflowStageStatus = 'completed' | 'blocked' | 'waiting' | 'skipped'

export interface OperatorSession {
  session_id: string
  principal: {
    subject: string
    display_name: string
  }
  absolute_expires_at: string
  idle_expires_at: string
  claims_refresh_due_at: string
  csrf_token: string
  effective_permissions: string[]
}

export interface PermissionMappingVersion {
  version_id: string
  revision: number
  rules: Array<{ claim_path: string; claim_value: string; permissions: string[] }>
  created_at: string
  created_by: string
}

export interface PermissionMappingsResponse {
  active: PermissionMappingVersion | null
  versions: PermissionMappingVersion[]
  recovery_mapping: {
    claim_path: string
    group_name: string
    permissions: string[]
  }
  permission_epoch: number
}

export interface EgressPolicyVersion {
  version_id: string
  revision: number
  rules: Array<{
    origin: { host: string; port: number }
    allowed_ip_networks: string[]
  }>
  created_at: string
  created_by: string
}

export interface EgressPoliciesResponse {
  active: EgressPolicyVersion | null
  versions: EgressPolicyVersion[]
}

export interface SecretHandleValidation {
  handle: { protocol_id: string; handle_id: string; purpose: string; version_id?: string | null }
  resolvable: boolean
  provider_version_id?: string | null
  checked_at: string
  reason_code?: string | null
}

export interface GovernanceDetails {
  intent_resolution?: Record<string, unknown> | null
  reasoning_summary?: Record<string, unknown> | null
  review_results?: Record<string, unknown>[]
  clarification_request?: Record<string, unknown> | null
}

export type ApprovalStatus = 'requested' | 'granted' | 'denied' | 'timed_out'

export type RunLifecycleState =
  | 'queued'
  | 'running'
  | 'finalizing'
  | 'succeeded'
  | 'failed'
  | 'timed_out'
  | 'cancel_requested'
  | 'cancelled'

/** Approval Queue view filter (queue scoping), not the approval lifecycle. */
export type ApprovalStatusFilter = 'all' | 'pending' | 'expired'

export interface RunSummary {
  run_id: string
  question: string
  outcome: ReceiptOutcome | null
  state?: RunLifecycleState
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
  outcome: ReceiptOutcome | null
  state?: RunLifecycleState
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

export interface AgentTemplateCapability {
  id: string
  name: string
  purpose: string
  description: string
}

export interface AgentConfigurationCapabilities {
  mode: 'development' | 'production'
  can_create: boolean
  can_import_manifest: boolean
  canonical_template: AgentTemplateCapability
}

export interface AgentDraftCapabilities {
  mode: 'development' | 'production'
  editable_modules: string[]
  lifecycle_tabs: string[]
  actions: {
    can_validate: boolean
    can_publish: boolean
    can_rollback: boolean
  }
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
  revision?: number
  capabilities?: AgentDraftCapabilities
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
    capabilities: AgentConfigurationCapabilities
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

export interface ProductionSecretHandle {
  protocol_id: string
  handle_id: string
  purpose: 'model_credential'
  version_id?: string | null
}

export interface PostgresEncryptedModelCredentialReference {
  type: 'postgres_encrypted'
  configured: true
}

export type ModelCredentialReference =
  | EnvironmentModelCredentialReference
  | ProductionSecretHandle
  | PostgresEncryptedModelCredentialReference

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
  credential_ref: ModelCredentialReference
  checked_env_vars?: string[]
  missing_env_vars?: string[]
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
  credential_ref: ModelCredentialReference
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
  credential_ref: ModelCredentialReference
  organization_env: string | null
  project_env: string | null
  timeout_seconds: number | null
  lifecycle_state: SharedModelConnectionLifecycleState
  created_at: string
  updated_at: string
  revision?: number
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
    credential_reference_type?: 'env' | 'postgres_encrypted'
  }
}

export type KnowledgeSourcePermission =
  | 'knowledge_source.view'
  | 'knowledge_source.edit'
  | 'knowledge_source.review'
  | 'knowledge_source.publish'
  | 'knowledge_source.archive'

export type KnowledgeSourceLifecycleState = 'ACTIVE' | 'ARCHIVED'

export interface KnowledgeSourceIntakeCapability {
  content_types: string[]
  max_file_bytes: number
  max_batch_files: number
  max_source_documents: number
}

export interface KnowledgeSourceProviderReadiness {
  state: 'ready' | 'degraded' | 'unavailable'
  revision: string | null
  blockers: string[]
}

export interface KnowledgeSourceProviderCapability {
  provider: string
  creation_supported: boolean
  intake: KnowledgeSourceIntakeCapability
  features: string[]
  readiness: KnowledgeSourceProviderReadiness
}

export interface KnowledgeSourceCapabilityProjection {
  schema_version: 'knowledge-source-api.v1'
  providers: KnowledgeSourceProviderCapability[]
}

export interface KnowledgeSourceActionBlocker {
  code: string
  detail: string
}

export interface KnowledgeSourceActionCapability {
  action: string
  allowed: boolean
  blockers: KnowledgeSourceActionBlocker[]
}

export interface KnowledgeSourceActionCapabilityProjection {
  source_id: string
  source_revision: number
  actions: KnowledgeSourceActionCapability[]
}

export interface KnowledgeSourceOperationProgress {
  current: number
  total: number
  unit: string
}

export interface KnowledgeSourceOperation {
  operation_id: string
  source_id: string
  command: string
  status: 'queued' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled'
  stage: string
  source_revision: number
  poll_after_ms: number
  progress: KnowledgeSourceOperationProgress | null
  outcome_code: string | null
  outcome_detail: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface KnowledgeSourceCursorPageInfo {
  limit: number
  next_cursor: string | null
  has_more: boolean
}

export interface KnowledgeSourceCursorPage<T> {
  data: T[]
  page: KnowledgeSourceCursorPageInfo
  summary: Record<string, number>
}

export interface KnowledgeSourceApiFieldError {
  location: string[]
  code: string
  detail: string
}

export interface KnowledgeSourceApiProblem {
  type: string
  title: string
  status: number
  code: string
  detail: string
  trace_id: string
  retryable: boolean
  current_revision: number | null
  field_errors: KnowledgeSourceApiFieldError[]
  blockers: KnowledgeSourceActionBlocker[]
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

export interface KnowledgeSourceDetailProjection {
  schema_version: 'knowledge-source-api.v1'
  source: KnowledgeSource
  revision: number
  summary: Record<string, number>
  action_capabilities: KnowledgeSourceActionCapabilityProjection
}

export interface KnowledgeSourceListItemProjection {
  source: KnowledgeSource
  revision: number
}

export interface KnowledgeSourceDocumentProjection {
  document_id: string
  revision_id: string
  filename: string
  content_type: string
  state: string
  candidate_state: 'candidate' | 'pending' | 'superseded' | 'unselected'
  safe_reason: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeSourceMetadataReviewProjection {
  review_id: string
  review_identity: string
  review_version: number
  document_id: string
  revision_id: string
  structured_build_id: string
  profile_revision_id: string
  scope: 'document_default' | 'rule_unit_override'
  state: 'needs_input' | 'ready_for_approval' | 'approved' | 'rejected'
  current: boolean
  canonical_anchor: string | null
  approved_metadata_revision_id: string | null
  parser_proposal: KnowledgeSourceMetadataValuesProjection
  current_draft: KnowledgeSourceMetadataValuesProjection
}

export interface KnowledgeSourceMetadataValuesProjection {
  authority: string | null
  effective_from: string | null
  effective_to: string | null
  taxonomy_id: string | null
  taxonomy_revision_id: string | null
  precedence_policy_revision_id: string | null
  precedence_authority_tier: string | null
  precedence_order: number | null
}

export interface KnowledgeSourceMetadataProfileProjection {
  metadata_scheme: 'insurance_rule.v2'
  profile_id: string
  profile_revision_id: string
  reference_only: boolean
  authority_values: readonly { code: string; label: string }[]
  taxonomy_id: string
  taxonomy_revision_id: string
  precedence_policy_revision_id: string
  precedence_authority_tier_values: readonly { code: string; label: string }[]
}

export interface KnowledgeSourceMetadataWorkbookFieldMergeProjection {
  scope: 'document_default' | 'rule_unit_override'
  canonical_anchor: string | null
  field: string
  classification: 'unchanged' | 'workbook_only' | 'server_only' | 'matching_change' | 'conflict'
  base_value: string | number | null
  server_value: string | number | null
  workbook_value: string | number | null
  proposed_value: string | number | null
}

export interface KnowledgeSourceMetadataWorkbookOverrideMergeProjection {
  canonical_anchor: string
  base_mode: 'inherit' | 'override'
  server_mode: 'inherit' | 'override'
  workbook_mode: 'inherit' | 'override'
  classification: 'unchanged' | 'workbook_only' | 'server_only' | 'matching_change' | 'conflict'
  proposed_mode: 'inherit' | 'override' | null
  override_reason: string | null
}

export interface KnowledgeSourceMetadataWorkbookValidationIssueProjection {
  sheet: string | null
  row: number | null
  field: string | null
  code: string
  suggested_action_key: string
}

export interface KnowledgeSourceMetadataWorkbookPreviewProjection {
  preview_id: string
  export_id: string
  state: 'validation_failed' | 'conflicts' | 'ready_to_apply' | 'applied' | 'expired' | 'stale'
  preview_identity: string | null
  conflict_count: number
  field_merges: KnowledgeSourceMetadataWorkbookFieldMergeProjection[]
  override_modes: KnowledgeSourceMetadataWorkbookOverrideMergeProjection[]
  validation_report: {
    total_error_count: number
    errors: KnowledgeSourceMetadataWorkbookValidationIssueProjection[]
  } | null
  created_at: string
  expires_at: string
}

export interface KnowledgeSourcePublicationValidationProjection {
  validation_id: string
  state: 'queued' | 'running' | 'prepared' | 'failed' | 'consumed'
  source_revision: number
  fencing_token: number
  source_draft_version_id: string
  generation_id: string | null
  safe_reason: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeSourcePublicationProjection {
  publication_id: string
  source_publication_seq: number
  source_draft_version_id: string
  source_snapshot_id: string
  generation_id: string
  validation_id: string
  published_at: string
  published_by: string
}

export interface KnowledgeSourceAuditProjection {
  audit_id: string
  event_type: string
  outcome: string
  actor_subject: string
  occurred_at: string
  target_type: string
  target_id: string
  metadata: Record<string, unknown>
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

export interface ReleaseRegistrySummary {
  release_id: string
  state: 'PREPARING' | 'FINALIZED'
  candidate_binding_sha256: string
  created_at: string
  finalized_at: string | null
  bundle_available: boolean
  artifact_names: string[]
}

export interface ReleasesResponse {
  releases: ReleaseRegistrySummary[]
}
