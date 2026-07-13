import type {
  ActiveAgentVersion,
  ApprovalStatusFilter,
  ApprovalsResponse,
  BusinessFlowSkillPackConfiguration,
  BusinessFlowSkillPackCreateRequest,
  BusinessFlowSkillPackUpdateRequest,
  CandidateKnowledgeSourceSnapshot,
  ConfigAgentsResponse,
  ConfigVersionsResponse,
  ContractBundle,
  DraftAgent,
  DraftValidationResponse,
  EvaluationCampaignCasesResponse,
  EvaluationCampaignsResponse,
  EvaluationCampaignSummary,
  EvaluationCampaignTrend,
  EvaluationProductionSampleCandidatesResponse,
  EvaluationProductionSamplePromotion,
  EvaluationProductionSamplePromotionRequest,
  EvaluationProductionSamplePromotionsResponse,
  FoundationKnowledgeSourceValidation,
  HandoffsResponse,
  HealthResponse,
  KnowledgeDocument,
  KnowledgeDocumentsResponse,
  KnowledgeIngestionJob,
  KnowledgeIngestionJobsResponse,
  InsuranceMetadataReview,
  InsuranceMetadataReviewsResponse,
  InsuranceMetadataWorkbookImportResponse,
  KnowledgeSource,
  KnowledgeSourceDeletionEligibility,
  KnowledgeSourceSnapshotManifest,
  KnowledgeSourcePublicationRecord,
  KnowledgeSourcePublicationValidation,
  KnowledgeSourcePublicationsResponse,
  KnowledgeSourcesResponse,
  KnowledgeUploadsResponse,
  ModelConnectionSmokeTestRecord,
  ModelConnectionValidationRecord,
  ModelConnectionsResponse,
  PublishedAgentVersion,
  QuarantinedKnowledgeUpload,
  RunDetail,
  RunPurposeFilter,
  RunsListResponse,
  SharedModelConnection,
  SharedModelConnectionDeletionEligibility,
  SharedModelConnectionReferenceSummary,
  StatsResponse,
  ValidationCaptureResponse,
  WorkflowStageConfig,
  WorkflowStageContextPreview,
  WorkflowStagePromptConfig,
  WorkflowTemplateDescriptor,
  WorkflowTemplatesResponse,
} from './types'

const BASE = '/api'
const CHAT_URL = import.meta.env.VITE_CHAT_URL as string | undefined ?? 'http://localhost:5174'

export function chatUrl(path: string): string {
  return `${CHAT_URL}${path}`
}

export class ApiError extends Error {
  readonly status: number
  readonly statusText: string
  readonly detail: unknown

  constructor(status: number, statusText: string, bodyText: string, detail: unknown) {
    super(`API error: ${status} ${statusText} ${bodyText}`)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.detail = detail
  }
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, options)
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '')
    let detail: unknown = null
    try {
      const parsed = JSON.parse(errText) as { detail?: unknown }
      detail = parsed.detail ?? null
    } catch {
      detail = null
    }
    throw new ApiError(resp.status, resp.statusText, errText, detail)
  }
  return resp.json() as Promise<T>
}

export function fetchRuns(params?: {
  outcome?: string
  run_purpose?: RunPurposeFilter
  search?: string
  limit?: number
  offset?: number
}): Promise<RunsListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.outcome) searchParams.set('outcome', params.outcome)
  if (params?.run_purpose) searchParams.set('run_purpose', params.run_purpose)
  if (params?.search) searchParams.set('search', params.search)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.offset) searchParams.set('offset', String(params.offset))
  const query = searchParams.toString()
  return fetchJson<RunsListResponse>(`${BASE}/runs${query ? `?${query}` : ''}`)
}

export function fetchRunDetail(runId: string): Promise<RunDetail> {
  return fetchJson<RunDetail>(`${BASE}/runs/${runId}`)
}

export function fetchValidationCapture(runId: string): Promise<ValidationCaptureResponse> {
  return fetchJson<ValidationCaptureResponse>(`${BASE}/runs/${runId}/validation-capture`)
}

export function fetchStats(): Promise<StatsResponse> {
  return fetchJson<StatsResponse>(`${BASE}/stats`)
}

export function fetchHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(`${BASE}/health`)
}

export function fetchHandoffs(): Promise<HandoffsResponse> {
  return fetchJson<HandoffsResponse>(`${BASE}/handoffs`)
}

export function fetchEvaluationCampaigns(): Promise<EvaluationCampaignsResponse> {
  return fetchJson<EvaluationCampaignsResponse>(`${BASE}/evaluation/campaigns`)
}

export function fetchEvaluationCampaign(campaignId: string): Promise<EvaluationCampaignSummary> {
  return fetchJson<EvaluationCampaignSummary>(`${BASE}/evaluation/campaigns/${campaignId}`)
}

export function fetchEvaluationCampaignCases(
  campaignId: string,
): Promise<EvaluationCampaignCasesResponse> {
  return fetchJson<EvaluationCampaignCasesResponse>(
    `${BASE}/evaluation/campaigns/${campaignId}/cases`,
  )
}

export function fetchEvaluationCampaignTrends(
  campaignId: string,
): Promise<EvaluationCampaignTrend> {
  return fetchJson<EvaluationCampaignTrend>(
    `${BASE}/evaluation/campaigns/${campaignId}/trends`,
  )
}

export function fetchEvaluationProductionSampleCandidates(): Promise<EvaluationProductionSampleCandidatesResponse> {
  return fetchJson<EvaluationProductionSampleCandidatesResponse>(
    `${BASE}/evaluation/production-samples/candidates`,
  )
}

export function fetchEvaluationProductionSamplePromotions(): Promise<EvaluationProductionSamplePromotionsResponse> {
  return fetchJson<EvaluationProductionSamplePromotionsResponse>(
    `${BASE}/evaluation/production-samples/promotions`,
  )
}

export function promoteEvaluationProductionSample(
  request: EvaluationProductionSamplePromotionRequest,
): Promise<EvaluationProductionSamplePromotion> {
  return fetchJson<EvaluationProductionSamplePromotion>(
    `${BASE}/evaluation/production-samples/promotions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  )
}

export function fetchApprovals(params?: {
  limit?: number
  offset?: number
  status?: ApprovalStatusFilter
}): Promise<ApprovalsResponse> {
  const searchParams = new URLSearchParams()
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.offset) searchParams.set('offset', String(params.offset))
  if (params?.status) searchParams.set('status', params.status)
  const query = searchParams.toString()
  return fetchJson<ApprovalsResponse>(`${BASE}/approvals${query ? `?${query}` : ''}`)
}

export function fetchConfigAgents(): Promise<ConfigAgentsResponse> {
  return fetchJson<ConfigAgentsResponse>(`${BASE}/config/agents`)
}

export function fetchKnowledgeSources(): Promise<KnowledgeSourcesResponse> {
  return fetchJson<KnowledgeSourcesResponse>(`${BASE}/config/knowledge-sources`)
}

export function fetchModelConnections(): Promise<ModelConnectionsResponse> {
  return fetchJson<ModelConnectionsResponse>(`${BASE}/config/model-connections`)
}

export function fetchWorkflowTemplates(): Promise<WorkflowTemplatesResponse> {
  return fetchJson<WorkflowTemplatesResponse>(`${BASE}/config/workflow-templates`)
}

export function fetchWorkflowTemplate(templateId: string): Promise<WorkflowTemplateDescriptor> {
  return fetchJson<WorkflowTemplateDescriptor>(`${BASE}/config/workflow-templates/${templateId}`)
}

export function updateWorkflowStages(
  agentId: string,
  draftId: string,
  payload: {
    template_descriptor_version?: string | null
    stages: WorkflowStageConfig[]
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/workflow-stages`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function previewWorkflowStageContext(
  agentId: string,
  draftId: string,
  stageId: string,
  payload: {
    prompt: WorkflowStagePromptConfig
    context: Record<string, boolean>
  },
): Promise<WorkflowStageContextPreview> {
  return fetchJson<WorkflowStageContextPreview>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/workflow-stages/${stageId}/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function createModelConnection(payload: {
  connection_id?: string | null
  display_name: string
  description?: string
  tags?: string[]
  provider: string
  model_identifier: string
  base_url?: string | null
  credential_ref: { type: 'env'; name: string }
  organization_env?: string | null
  project_env?: string | null
  timeout_seconds?: number | null
}): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchModelConnection(connectionId: string): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}`)
}

export function updateModelConnection(
  connectionId: string,
  payload: {
    display_name?: string | null
    description?: string | null
    tags?: string[] | null
    provider?: string | null
    model_identifier?: string | null
    base_url?: string | null
    credential_ref?: { type: 'env'; name: string } | null
    organization_env?: string | null
    project_env?: string | null
    timeout_seconds?: number | null
    confirm_impact?: boolean
  },
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function archiveModelConnection(
  connectionId: string,
  payload: { reason: string },
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function restoreModelConnection(
  connectionId: string,
  payload: { reason?: string | null } = {},
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchModelConnectionReferences(
  connectionId: string,
): Promise<SharedModelConnectionReferenceSummary> {
  return fetchJson<SharedModelConnectionReferenceSummary>(
    `${BASE}/config/model-connections/${connectionId}/references`,
  )
}

export function fetchModelConnectionDeletionEligibility(
  connectionId: string,
): Promise<SharedModelConnectionDeletionEligibility> {
  return fetchJson<SharedModelConnectionDeletionEligibility>(
    `${BASE}/config/model-connections/${connectionId}/deletion-eligibility`,
  )
}

export function deleteModelConnection(
  connectionId: string,
  payload: { reason: string },
): Promise<SharedModelConnectionDeletionEligibility> {
  return fetchJson<SharedModelConnectionDeletionEligibility>(
    `${BASE}/config/model-connections/${connectionId}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function validateModelConnection(
  connectionId: string,
): Promise<ModelConnectionValidationRecord> {
  return fetchJson<ModelConnectionValidationRecord>(
    `${BASE}/config/model-connections/${connectionId}/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function smokeTestModelConnection(
  connectionId: string,
): Promise<ModelConnectionSmokeTestRecord> {
  return fetchJson<ModelConnectionSmokeTestRecord>(
    `${BASE}/config/model-connections/${connectionId}/smoke-test`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function fetchKnowledgeSource(sourceId: string): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}`)
}

export function createKnowledgeSource(payload: {
  source_id?: string
  name: string
  provider: string
  params?: Record<string, unknown>
}): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function archiveKnowledgeSource(
  sourceId: string,
  payload: { reason: string },
): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function restoreKnowledgeSource(
  sourceId: string,
  payload: { reason?: string | null } = {},
): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchKnowledgeSourceDeletionEligibility(
  sourceId: string,
): Promise<KnowledgeSourceDeletionEligibility> {
  return fetchJson<KnowledgeSourceDeletionEligibility>(
    `${BASE}/config/knowledge-sources/${sourceId}/deletion-eligibility`,
  )
}

export function permanentlyDeleteKnowledgeSource(
  sourceId: string,
  payload: { reason: string },
): Promise<KnowledgeSourceDeletionEligibility> {
  return fetchJson<KnowledgeSourceDeletionEligibility>(`${BASE}/config/knowledge-sources/${sourceId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchKnowledgeDocuments(sourceId: string): Promise<KnowledgeDocumentsResponse> {
  return fetchJson<KnowledgeDocumentsResponse>(`${BASE}/config/knowledge-sources/${sourceId}/documents`)
}

export function fetchQuarantinedKnowledgeUploads(sourceId: string): Promise<KnowledgeUploadsResponse> {
  return fetchJson<KnowledgeUploadsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/quarantined-uploads`,
  )
}

export function fetchKnowledgeIngestionJobs(sourceId: string): Promise<KnowledgeIngestionJobsResponse> {
  return fetchJson<KnowledgeIngestionJobsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/ingestion-jobs`,
  )
}

export function retryKnowledgeIngestionJob(
  sourceId: string,
  jobId: string,
): Promise<KnowledgeIngestionJob> {
  return fetchJson<KnowledgeIngestionJob>(
    `${BASE}/config/knowledge-sources/${sourceId}/ingestion-jobs/${jobId}/retry`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function fetchCandidateKnowledgeSourceSnapshot(
  sourceId: string,
): Promise<CandidateKnowledgeSourceSnapshot> {
  return fetchJson<CandidateKnowledgeSourceSnapshot>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot`,
  )
}

export function validateCandidateKnowledgeSourceSnapshotFoundation(
  sourceId: string,
): Promise<FoundationKnowledgeSourceValidation> {
  return fetchJson<FoundationKnowledgeSourceValidation>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot/validate-foundation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function freezeCandidateKnowledgeSourceSnapshot(
  sourceId: string,
  payload: { validation_id: string },
): Promise<KnowledgeSourceSnapshotManifest> {
  return fetchJson<KnowledgeSourceSnapshotManifest>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot/freeze`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function validateKnowledgeSourcePublication(
  sourceId: string,
  payload: { smoke_query: string },
): Promise<KnowledgeSourcePublicationValidation> {
  return fetchJson<KnowledgeSourcePublicationValidation>(
    `${BASE}/config/knowledge-sources/${sourceId}/publication/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function publishKnowledgeSource(
  sourceId: string,
  payload: { validation_id: string; change_note: string },
): Promise<KnowledgeSourcePublicationRecord> {
  return fetchJson<KnowledgeSourcePublicationRecord>(
    `${BASE}/config/knowledge-sources/${sourceId}/publication/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchKnowledgeSourcePublications(
  sourceId: string,
): Promise<KnowledgeSourcePublicationsResponse> {
  return fetchJson<KnowledgeSourcePublicationsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/publications`,
  )
}

export function fetchInsuranceMetadataReviews(
  sourceId: string,
  options: { limit?: number; cursor?: string; state?: InsuranceMetadataReview['state'] } = {},
): Promise<InsuranceMetadataReviewsResponse> {
  const query = new URLSearchParams()
  query.set('limit', String(options.limit ?? 50))
  if (options.cursor) query.set('cursor', options.cursor)
  if (options.state) query.set('state', options.state)
  return fetchJson<InsuranceMetadataReviewsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/metadata-reviews?${query.toString()}`,
  )
}

export function importInsuranceMetadataWorkbook(
  sourceId: string,
  payload: {
    filename: string
    content_type: string
    content_base64: string
    document_id: string
    revision_id: string
  },
): Promise<InsuranceMetadataWorkbookImportResponse> {
  return fetchJson<InsuranceMetadataWorkbookImportResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/metadata-workbooks/import`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function resolveInsuranceMetadataReview(
  sourceId: string,
  review: InsuranceMetadataReview,
  action: 'approve' | 'correct' | 'reject',
  payload: { reason: string; corrections?: Record<string, string | number | null> },
): Promise<InsuranceMetadataReview> {
  return fetchJson<InsuranceMetadataReview>(
    `${BASE}/config/knowledge-sources/${sourceId}/metadata-reviews/${review.review_id}/${action}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_review_version: review.review_version,
        expected_review_identity: review.review_identity,
        reason: payload.reason,
        corrections: payload.corrections ?? {},
      }),
    },
  )
}

export function uploadKnowledgeDocument(
  sourceId: string,
  payload: {
    filename: string
    content_type: string
    content_base64: string
  },
): Promise<QuarantinedKnowledgeUpload> {
  return fetchJson<QuarantinedKnowledgeUpload>(`${BASE}/config/knowledge-sources/${sourceId}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function uploadKnowledgeDocuments(
  sourceId: string,
  payload: {
    documents: {
      filename: string
      content_type: string
      content_base64: string
    }[]
  },
): Promise<KnowledgeUploadsResponse> {
  return fetchJson<KnowledgeUploadsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/documents/batch`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function updateKnowledgeDocumentRoutingMetadata(
  sourceId: string,
  documentId: string,
  payload: {
    routing_metadata: Record<string, unknown>
  },
): Promise<KnowledgeDocument> {
  return fetchJson<KnowledgeDocument>(
    `${BASE}/config/knowledge-sources/${sourceId}/documents/${documentId}/routing-metadata`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function bindKnowledgeSourceToDraft(
  agentId: string,
  draftId: string,
  payload: {
    source_id: string
    binding_id?: string | null
    alias?: string | null
    failure_mode?: 'required' | 'advisory'
    fusion_weight?: number
    top_k?: number | null
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/knowledge-bindings`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function unbindKnowledgeSourceFromDraft(
  agentId: string,
  draftId: string,
  bindingId: string,
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/knowledge-bindings/${bindingId}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function importConfigAgent(payload: {
  manifest_path: string
}): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchConfigDraft(agentId: string, draftId: string): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/${agentId}/drafts/${draftId}`)
}

export function updateConfigDraft(
  agentId: string,
  draftId: string,
  payload: { display_name?: string; purpose?: string },
): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/${agentId}/drafts/${draftId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchConfigDraftContract(
  agentId: string,
  draftId: string,
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(`${BASE}/config/agents/${agentId}/drafts/${draftId}/contract`)
}

export function fetchConfigDraftSkills(
  agentId: string,
  draftId: string,
): Promise<BusinessFlowSkillPackConfiguration> {
  return fetchJson<BusinessFlowSkillPackConfiguration>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/skills`,
  )
}

export function createConfigDraftSkillPack(
  agentId: string,
  draftId: string,
  payload: BusinessFlowSkillPackCreateRequest,
): Promise<BusinessFlowSkillPackConfiguration> {
  return fetchJson<BusinessFlowSkillPackConfiguration>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/skills/business-flows`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function updateConfigDraftSkillPack(
  agentId: string,
  draftId: string,
  packId: string,
  payload: BusinessFlowSkillPackUpdateRequest,
): Promise<BusinessFlowSkillPackConfiguration> {
  return fetchJson<BusinessFlowSkillPackConfiguration>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/skills/business-flows/${packId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function deleteConfigDraftSkillPack(
  agentId: string,
  draftId: string,
  packId: string,
): Promise<BusinessFlowSkillPackConfiguration> {
  return fetchJson<BusinessFlowSkillPackConfiguration>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/skills/business-flows/${packId}`,
    {
      method: 'DELETE',
    },
  )
}

export function updateConfigDraftContract(
  agentId: string,
  draftId: string,
  payload: {
    agent_yaml?: string
    policy_yaml?: string
    tools_yaml?: string
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(`${BASE}/config/agents/${agentId}/drafts/${draftId}/contract`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function validateConfigDraft(
  agentId: string,
  draftId: string,
  payload: { question: string; full_capture?: boolean; retain_for_audit?: boolean },
): Promise<DraftValidationResponse> {
  return fetchJson<DraftValidationResponse>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function publishConfigDraft(
  agentId: string,
  draftId: string,
  payload: { validation_run_id?: string | null },
): Promise<PublishedAgentVersion> {
  return fetchJson<PublishedAgentVersion>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchConfigVersions(agentId: string): Promise<ConfigVersionsResponse> {
  return fetchJson<ConfigVersionsResponse>(`${BASE}/config/agents/${agentId}/versions`)
}

export function rollbackConfigVersion(
  agentId: string,
  versionId: string,
): Promise<ActiveAgentVersion> {
  return fetchJson<ActiveAgentVersion>(
    `${BASE}/config/agents/${agentId}/versions/${versionId}/rollback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
}

export function approveRun(
  runId: string,
  approvalId: string,
): Promise<RunDetail> {
  return fetchJson<RunDetail>(`${BASE}/runs/${runId}/approvals/${approvalId}/approve`, {
    method: 'POST'
  })
}

export function denyRun(
  runId: string,
  approvalId: string,
): Promise<RunDetail> {
  return fetchJson<RunDetail>(`${BASE}/runs/${runId}/approvals/${approvalId}/deny`, {
    method: 'POST'
  })
}
