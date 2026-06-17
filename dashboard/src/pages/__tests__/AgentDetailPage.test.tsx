// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bindKnowledgeSourceToDraft,
  createModelConnection,
  fetchValidationCapture,
  fetchRuns,
  fetchWorkflowTemplate,
  fetchKnowledgeSources,
  fetchModelConnections,
  previewWorkflowStageContext,
  updateConfigDraft,
  updateConfigDraftContract,
  updateWorkflowStages,
  validateConfigDraft,
} from '../../api/client'
import type { DraftAgent, DraftValidationResponse } from '../../api/types'
import { AgentDetailPage } from '../AgentDetailPage'

vi.mock('../../api/client', () => ({
  bindKnowledgeSourceToDraft: vi.fn(),
  chatUrl: (path: string) => `http://localhost:5174${path}`,
  createModelConnection: vi.fn(),
  fetchRuns: vi.fn(),
  fetchValidationCapture: vi.fn(),
  fetchWorkflowTemplate: vi.fn(),
  fetchKnowledgeSources: vi.fn(),
  fetchModelConnections: vi.fn(),
  previewWorkflowStageContext: vi.fn(),
  publishConfigDraft: vi.fn(),
  rollbackConfigVersion: vi.fn(),
  unbindKnowledgeSourceFromDraft: vi.fn(),
  updateConfigDraft: vi.fn(),
  updateConfigDraftContract: vi.fn(),
  updateWorkflowStages: vi.fn(),
  validateConfigDraft: vi.fn(),
}))

const refreshDraft = vi.fn()
const refreshVersions = vi.fn()
let mockDraft: DraftAgent = {
  agent_id: 'agent-1',
  draft_id: 'draft-1',
  display_name: 'Insurance Agent',
  purpose: 'Answer governed insurance questions.',
  created_at: '2026-05-28T00:00:00Z',
  updated_at: '2026-05-28T00:00:00Z',
  created_by: 'dashboard',
  updated_by: 'dashboard',
  version_id: null,
  validation_records: [],
  operation_audit: [],
}
let mockContract = {
  agent_yaml: 'name: insurance\nmemory:\n  provider: local\n',
  policy_yaml: '',
  tools_yaml: '',
  extra_files: {},
  advanced_fields: {},
}
let mockVersions: Array<{
  agent_id: string
  version_id: string
  source_draft_id: string
  validation_run_id: string
  display_name: string
  purpose: string
  published_at: string
  published_by: string
  operation_audit: []
}> = []
let mockActiveVersionId: string | null = null

vi.mock('../../hooks/useConfigDraft', () => ({
  useConfigDraft: () => ({
    draft: mockDraft,
    contract: mockContract,
    loading: false,
    error: null,
    refresh: refreshDraft,
  }),
}))

vi.mock('../../hooks/useConfigVersions', () => ({
  useConfigVersions: () => ({
    versions: mockVersions,
    activeVersionId: mockActiveVersionId,
    loading: false,
    error: null,
    refresh: refreshVersions,
  }),
}))

function renderPage(initialEntry = '/agents/agent-1/drafts/draft-1') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/agents/:agentId/drafts/:draftId" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function latestSavedAgentYaml(): string {
  const payload = vi.mocked(updateConfigDraftContract).mock.calls.at(-1)?.[2]
  if (!payload?.agent_yaml) throw new Error('No agent_yaml payload was saved.')
  return payload.agent_yaml
}

describe('AgentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchModelConnections).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(updateConfigDraft).mockImplementation(async (_agentId, _draftId, payload) => ({
      ...mockDraft,
      ...payload,
    }))
    vi.mocked(updateConfigDraftContract).mockImplementation(async (_agentId, _draftId, payload) => ({
      ...mockContract,
      ...payload,
    }))
    vi.mocked(fetchRuns).mockResolvedValue({
      data: [
        {
          run_id: 'run-production-1',
          question: 'What documents are required?',
          outcome: 'ANSWERED_WITH_CITATIONS',
          run_purpose: 'production',
          agent_id: 'agent-1',
          agent_version_id: 'version-1',
          draft_id: null,
          created_at: '2026-05-28T02:00:00Z',
          updated_at: '2026-05-28T02:00:00Z',
          approval_status: null,
          error_code: null,
        },
        {
          run_id: 'run-validation-1',
          question: 'Validation question',
          outcome: 'REFUSED_NO_EVIDENCE',
          run_purpose: 'validation',
          agent_id: 'agent-1',
          agent_version_id: null,
          draft_id: 'draft-1',
          created_at: '2026-05-28T01:00:00Z',
          updated_at: '2026-05-28T01:00:00Z',
          approval_status: null,
          error_code: null,
        },
        {
          run_id: 'run-other-agent',
          question: 'Other agent question',
          outcome: 'ANSWERED_WITH_CITATIONS',
          run_purpose: 'production',
          agent_id: 'agent-2',
          agent_version_id: 'version-other',
          draft_id: null,
          created_at: '2026-05-28T03:00:00Z',
          updated_at: '2026-05-28T03:00:00Z',
          approval_status: null,
          error_code: null,
        },
      ],
      meta: { total: 3, limit: 50, offset: 0 },
    })
    vi.mocked(createModelConnection).mockRejectedValue(new Error('not mocked'))
    vi.mocked(fetchWorkflowTemplate).mockResolvedValue({
      name: 'react_enterprise_qa',
      description: 'Controlled ReAct enterprise question answering.',
      descriptor_version: 'react_enterprise_qa.v1',
      stages: [
        {
          id: 'plan',
          label: 'Plan',
          description: 'Propose the next governed action.',
          predecessors: [],
          successors: ['response'],
          branch_conditions: { response: 'STOP' },
          governed_handoff_points: [],
          editable_prompt_fields: ['business_context', 'task_instructions', 'output_preferences'],
          context_options: ['include_agent_purpose'],
          input_summary: 'Question.',
          output_summary: 'Action proposal.',
          model_bearing: true,
          required: true,
        },
        {
          id: 'response',
          label: 'Response',
          description: 'Project governed outcome.',
          predecessors: ['plan'],
          successors: [],
          branch_conditions: {},
          governed_handoff_points: [],
          editable_prompt_fields: ['business_context', 'task_instructions', 'output_preferences'],
          context_options: ['include_outcome'],
          input_summary: 'Outcome.',
          output_summary: 'Final response.',
          model_bearing: false,
          required: true,
        },
      ],
    })
    vi.mocked(updateWorkflowStages).mockResolvedValue({
      ...mockContract,
      agent_yaml: 'name: insurance\nworkflow:\n  template: react_enterprise_qa\n',
    })
    vi.mocked(previewWorkflowStageContext).mockResolvedValue({
      stage_id: 'plan',
      stage_label: 'Plan',
      harness_control_prompt_summary: 'Harness control prompt retained.',
      structured_control_context: { agent_purpose: 'Answer governed insurance questions.' },
      business_context_addendum: {
        present: true,
        text: 'Business Context:\nClaims context',
        fields: ['business_context'],
      },
      summary: { stage_id: 'plan', prompt_fields: ['business_context'] },
    })
    mockDraft = {
      agent_id: 'agent-1',
      draft_id: 'draft-1',
      display_name: 'Insurance Agent',
      purpose: 'Answer governed insurance questions.',
      created_at: '2026-05-28T00:00:00Z',
      updated_at: '2026-05-28T00:00:00Z',
      created_by: 'dashboard',
      updated_by: 'dashboard',
      version_id: null,
      validation_records: [],
      operation_audit: [],
    }
    mockContract = {
      agent_yaml: 'name: insurance\nmemory:\n  provider: local\n',
      policy_yaml: '',
      tools_yaml: '',
      extra_files: {},
      advanced_fields: {},
    }
    mockVersions = []
    mockActiveVersionId = null
  })

  it('opens Agent Overview by default with identity and monitor summary', async () => {
    mockVersions = [
      {
        agent_id: 'agent-1',
        version_id: 'version-1',
        source_draft_id: 'draft-1',
        validation_run_id: 'run-validation-1',
        display_name: 'Insurance Agent',
        purpose: 'Answer governed insurance questions.',
        published_at: '2026-05-28T01:00:00Z',
        published_by: 'dashboard',
        operation_audit: [],
      },
    ]
    mockActiveVersionId = 'version-1'

    renderPage()

    expect(screen.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('Agent Overview')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Insurance Agent')).toBeInTheDocument()
    expect(await screen.findByText('Production Runs')).toBeInTheDocument()
    expect(screen.getByText('Answered Rate')).toBeInTheDocument()
    expect(screen.getByText('Recent Agent Runs')).toBeInTheDocument()
    expect(screen.getByText('What documents are required?')).toBeInTheDocument()
    expect(screen.queryByText('Other agent question')).not.toBeInTheDocument()
  })

  it('saves overview identity fields through the draft configuration API', async () => {
    renderPage()

    fireEvent.change(screen.getByDisplayValue('Insurance Agent'), {
      target: { value: 'Claims QA Agent' },
    })
    fireEvent.change(screen.getByDisplayValue('Answer governed insurance questions.'), {
      target: { value: 'Handle governed claims questions.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(updateConfigDraft).toHaveBeenCalledWith('agent-1', 'draft-1', {
        display_name: 'Claims QA Agent',
        purpose: 'Handle governed claims questions.',
      })
    })
  })

  it('shows validation busy state while a validation run is running', async () => {
    let resolveValidation: (value: DraftValidationResponse) => void = () => {}
    vi.mocked(validateConfigDraft).mockReturnValue(
      new Promise<DraftValidationResponse>((resolve) => {
        resolveValidation = resolve
      }),
    )

    renderPage()
    fireEvent.click(screen.getByText('Validate & Test'))
    fireEvent.change(screen.getByPlaceholderText('Enter a test question...'), {
      target: { value: 'What documents are required?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run Validation' }))

    expect(screen.getByRole('button', { name: 'Running Validation...' })).toBeDisabled()

    const validationResponse: DraftValidationResponse = {
      validation_id: 'validation-1',
      run_id: 'run-1',
      status: 'completed',
      outcome: 'ANSWERED_WITH_CITATIONS',
      run_purpose: 'validation',
      agent_id: 'agent-1',
      draft_id: 'draft-1',
      links: { run_detail: '/runs/run-1', trace: '', receipt: '' },
    }
    resolveValidation(validationResponse)

    await waitFor(() => expect(refreshDraft).toHaveBeenCalled())
  })

  it('submits validation capture options from Validate & Test', async () => {
    vi.mocked(validateConfigDraft).mockResolvedValue({
      validation_id: 'validation-1',
      run_id: 'run-1',
      status: 'completed',
      outcome: 'ANSWERED_WITH_CITATIONS',
      run_purpose: 'validation',
      agent_id: 'agent-1',
      draft_id: 'draft-1',
      links: {
        run_detail: '/runs/run-1',
        trace: '',
        receipt: '',
        validation_capture: '/api/runs/run-1/validation-capture',
      },
      trace_capture: {
        mode: 'full_capture',
        validation_capture: {
          capture_id: 'vcap_1',
          run_id: 'run-1',
          draft_id: 'draft-1',
          created_at: '2026-05-28T01:00:00Z',
          expires_at: '2026-05-29T01:00:00Z',
          created_by: 'dashboard',
          retention_class: 'sensitive_validation_capture',
          artifact_path: 'validation_captures/vcap_1/capture.json',
          retain_for_audit: true,
          redaction_metadata: {},
          exclusion_metadata: {},
        },
      },
    })

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')
    fireEvent.change(screen.getByPlaceholderText('Enter a test question...'), {
      target: { value: 'What documents are required?' },
    })
    fireEvent.click(screen.getByLabelText('Full stage capture'))
    fireEvent.click(screen.getByLabelText('Retain for audit'))
    fireEvent.click(screen.getByRole('button', { name: 'Run Validation' }))

    await waitFor(() => {
      expect(validateConfigDraft).toHaveBeenCalledWith('agent-1', 'draft-1', {
        question: 'What documents are required?',
        full_capture: true,
        retain_for_audit: true,
      })
    })
  })

  it('restores the Validate & Test module from the route query', () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByPlaceholderText('Enter a test question...')).toBeInTheDocument()
  })

  it('presents validation as a draft validation workspace', () => {
    mockDraft = {
      ...mockDraft,
      validation_records: [
        {
          validation_id: 'validation-1',
          draft_id: 'draft-1',
          run_id: 'run-validation-1',
          status: 'ANSWERED_WITH_CITATIONS',
          summary: 'Validation completed with citations.',
          errors: [],
          created_at: '2026-05-28T01:00:00Z',
          validation_capture_id: 'vcap_1',
        },
      ],
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByRole('heading', { name: 'Draft Readiness' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Run Validation' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Latest Validation Result' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Validation History' })).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(['Quick', 'Test'].join(' ')))).not.toBeInTheDocument()
    expect(screen.getByText('Capture available')).toBeInTheDocument()
  })

  it('loads safe validation capture sections for the latest validation run', async () => {
    mockDraft = {
      ...mockDraft,
      validation_records: [
        {
          validation_id: 'validation-1',
          draft_id: 'draft-1',
          run_id: 'run-validation-1',
          status: 'ANSWERED_WITH_CITATIONS',
          summary: 'Validation completed with citations.',
          errors: [],
          created_at: '2026-05-28T01:00:00Z',
          validation_capture_id: 'vcap_1',
        },
      ],
    }
    vi.mocked(fetchValidationCapture).mockResolvedValue({
      metadata: {
        capture_id: 'vcap_1',
        run_id: 'run-validation-1',
        draft_id: 'draft-1',
        created_at: '2026-05-28T01:00:00Z',
        expires_at: '2026-05-29T01:00:00Z',
        created_by: 'dashboard',
        retention_class: 'sensitive_validation_capture',
        artifact_path: 'validation_captures/vcap_1/capture.json',
        retain_for_audit: false,
        redaction_metadata: {},
        exclusion_metadata: {},
      },
      payload: {
        capture_contract_version: 'validation_capture.v2',
        source: {
          run_id: 'run-validation-1',
          run_purpose: 'validation',
          agent_id: 'agent-1',
          agent_version_id: null,
          draft_id: 'draft-1',
          validation_id: 'validation-1',
          template_name: 'react_enterprise_qa',
          template_descriptor_version: 'react_enterprise_qa.v1',
          stage_configuration_source_type: 'draft',
          stage_configuration_source_reference: 'draft-1',
          effective_stage_configuration_ref: 'snapshot-1',
        },
        stage_prompt_values: [
          {
            stage_id: 'plan',
            stage_label: 'Plan',
            prompt_values: { business_context: '[projection]' },
            prompt_field_names: ['business_context'],
            prompt_character_count: 12,
            redaction_applied: false,
            source: 'draft',
          },
        ],
        context_configuration: [
          {
            stage_id: 'plan',
            stage_label: 'Plan',
            selected_context_options: ['include_agent_purpose'],
            available_context_options: ['include_agent_purpose'],
          },
        ],
        context_applications: [
          {
            stage_id: 'plan',
            stage_label: 'Plan',
            summary: { option_count: 1 },
          },
        ],
        stage_results: [
          {
            stage_id: 'plan',
            stage_label: 'Plan',
            status: 'completed',
            outcome: null,
            summary: { produced_fact_count: 1 },
            produced_fact_refs: ['fact-1'],
          },
        ],
        failure_diagnostics: [],
        llm_interactions: [
          {
            stage_id: 'plan',
            stage_label: 'Plan',
            role: 'react_planner',
            provider: 'openai_compatible',
            model: 'planner-test',
            request_json: {
              response_format: 'json',
              messages: [{ role: 'user', content: '{"question":"Q"}' }],
            },
            response_json: { action_type: 'plan_retrieval' },
            response_content_length: 32,
            response_json_parse_error_code: null,
          },
        ],
        result_summary: {
          outcome: 'ANSWERED_WITH_CITATIONS',
          final_output: 'Validation answer.',
          final_output_length: 18,
          fact_refs: ['fact-1'],
          approval_pause: null,
          clarification_need: null,
        },
        exclusions: {
          excluded_categories: ['raw_prompt', 'raw_context'],
          sanitizer_version: 'validation_capture.v2',
          redacted_secret_count: 0,
          dropped_unsafe_key_count: 0,
          redaction_applied: false,
        },
      },
    })

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')
    fireEvent.click(screen.getByRole('button', { name: 'Load Validation Capture' }))

    expect(await screen.findByText('Source')).toBeInTheDocument()
    expect(screen.getByText('Stage Review')).toBeInTheDocument()
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('Reveal Prompt Values')).toBeInTheDocument()
    expect(screen.getByText('Configured Context')).toBeInTheDocument()
    expect(screen.getByText('Applied Context')).toBeInTheDocument()
    expect(screen.getByText('Stage Result')).toBeInTheDocument()
    expect(screen.getByText('LLM Input/Output JSON')).toBeInTheDocument()
    expect(screen.getByText('react_planner')).toBeInTheDocument()
    expect(screen.getByText('Result Summary')).toBeInTheDocument()
    expect(screen.getByText('Exclusions')).toBeInTheDocument()
    expect(fetchValidationCapture).toHaveBeenCalledWith('run-validation-1')
  })

  it('loads workflow descriptor and saves stage prompt configuration', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    type: memory
`,
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=workflow')

    expect(await screen.findByText('Stage Inspector')).toBeInTheDocument()
    expect(screen.getByText('Read-Only Relationship Map')).toBeInTheDocument()
    expect(screen.getAllByText('Plan').length).toBeGreaterThan(0)
    fireEvent.click(await screen.findByRole('button', { name: 'Explain Business Context' }))
    expect(screen.getByText(/Adds domain-specific context/)).toBeInTheDocument()
    fireEvent.change(await screen.findByLabelText('Business Context'), {
      target: { value: 'Claims context' },
    })
    fireEvent.click(screen.getByLabelText('include_agent_purpose'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))

    await waitFor(() => {
      expect(previewWorkflowStageContext).toHaveBeenCalledWith('agent-1', 'draft-1', 'plan', {
        prompt: {
          business_context: 'Claims context',
          task_instructions: [],
          output_preferences: [],
        },
        context: { include_agent_purpose: true },
      })
    })

    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    await waitFor(() => {
      expect(updateWorkflowStages).toHaveBeenCalledWith('agent-1', 'draft-1', {
        template_descriptor_version: 'react_enterprise_qa.v1',
        stages: [
          {
            id: 'plan',
            prompt: {
              business_context: 'Claims context',
              task_instructions: [],
              output_preferences: [],
            },
            context: { include_agent_purpose: true },
          },
          {
            id: 'response',
            prompt: {
              business_context: '',
              task_instructions: [],
              output_preferences: [],
            },
            context: {},
          },
        ],
      })
    })
  })

  it('saves Workflow core settings through the draft contract API', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: sqlite:///runs/config/checkpoints.db
`,
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=workflow')
    const checkpointerUri = await screen.findByLabelText('Checkpointer URI')

    fireEvent.change(checkpointerUri, {
      target: { value: 'sqlite:///runs/config/checkpoints-v2.db' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Core' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    expect(latestSavedAgentYaml()).toContain('uri: "sqlite:///runs/config/checkpoints-v2.db"')
  })

  it('shows chat entry actions for the active Published Agent version', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: 'name: insurance\ncustomer:\n  adapter: ./customer_adapter.py\nmemory:\n  provider: local\n',
    }
    mockVersions = [
      {
        agent_id: 'agent-1',
        version_id: 'version-1',
        source_draft_id: 'draft-1',
        validation_run_id: 'run-1',
        display_name: 'Insurance Agent',
        purpose: 'Answer governed insurance questions.',
        published_at: '2026-05-28T01:00:00Z',
        published_by: 'dashboard',
        operation_audit: [],
      },
    ]
    mockActiveVersionId = 'version-1'

    renderPage('/agents/agent-1/drafts/draft-1?tab=versions')

    expect(screen.getByRole('link', { name: 'Open in Operator Chat' })).toHaveAttribute(
      'href',
      'http://localhost:5174/operator/agents/agent-1/new',
    )
    expect(screen.getByRole('link', { name: 'Open in Customer Chat' })).toHaveAttribute(
      'href',
      'http://localhost:5174/customer/agents/agent-1',
    )
  })

  it('binds a shared knowledge source into the draft contract', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({
      data: [
        {
          source_id: 'ks_published',
          name: 'Shared Published Policies',
          provider: 'local_index',
          lifecycle_state: 'ACTIVE',
          params: { ingestion_model: { provider: 'deterministic', name: 'routing' } },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          source_draft_version_id: 'ksdraft_1',
          latest_snapshot_id: 'kssnapshot_1',
          published_snapshot_id: 'kssnapshot_1',
          publication_count: 1,
          document_count: 1,
          ready_document_count: 1,
        },
        {
          source_id: 'ks_unpublished',
          name: 'Draft Policies',
          provider: 'local_index',
          lifecycle_state: 'ACTIVE',
          params: { ingestion_model: { provider: 'deterministic', name: 'routing' } },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          source_draft_version_id: 'ksdraft_2',
          latest_snapshot_id: 'kssnapshot_2',
          published_snapshot_id: null,
          publication_count: 0,
          document_count: 1,
          ready_document_count: 1,
        },
        {
          source_id: 'ks_archived_published',
          name: 'Archived Published Policies',
          provider: 'local_index',
          lifecycle_state: 'ARCHIVED',
          params: { ingestion_model: { provider: 'deterministic', name: 'routing' } },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          source_draft_version_id: 'ksdraft_3',
          latest_snapshot_id: 'kssnapshot_3',
          published_snapshot_id: 'kssnapshot_3',
          publication_count: 1,
          document_count: 1,
          ready_document_count: 1,
        },
      ],
      meta: { total: 3 },
    })
    vi.mocked(bindKnowledgeSourceToDraft).mockResolvedValue({
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'package_knowledge_sources: []',
        'knowledge_bindings:',
        '- binding_id: ks_published_binding',
        '  source_ref:',
        '    scope: shared',
        '    source_id: ks_published',
        '  failure_mode: required',
        '  fusion_weight: 1',
        '',
      ].join('\n'),
    })

    renderPage()
    fireEvent.click(screen.getByText('Knowledge'))
    expect(await screen.findByText(/Shared Published Policies/)).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Draft Policies/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Archived Published Policies/ })).not.toBeInTheDocument()
    expect(screen.getByText('1 published available')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Bind Source' }))

    await waitFor(() => {
      expect(bindKnowledgeSourceToDraft).toHaveBeenCalledWith('agent-1', 'draft-1', {
        source_id: 'ks_published',
        alias: '',
        failure_mode: 'required',
        fusion_weight: 1,
      })
    })
    expect(refreshDraft).toHaveBeenCalled()
  })

  it('saves Knowledge retrieval settings through the draft contract API', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'retrieval:',
        '  strategy: single_step',
        '  top_k: 3',
        '  min_score: 0.2',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=knowledge')
    expect(await screen.findByText('Global Retrieval Settings')).toBeInTheDocument()

    fireEvent.change(screen.getByDisplayValue('single_step'), {
      target: { value: 'agentic' },
    })
    fireEvent.change(screen.getByDisplayValue('3'), {
      target: { value: '8' },
    })

    expect(screen.queryByRole('button', { name: 'Save Workflow' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Knowledge' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain('strategy: agentic')
    expect(savedYaml).toContain('top_k: 8')
  })

  it.each([
    {
      tab: 'tools',
      label: 'Tools Config File',
      initialYaml: ['name: insurance', 'tools:', '  file: config/tools.yaml', ''].join('\n'),
      value: 'config/tools-v2.yaml',
      expected: 'file: config/tools-v2.yaml',
    },
    {
      tab: 'policy',
      label: 'Policy File',
      initialYaml: ['name: insurance', 'policy:', '  file: config/policy.yaml', ''].join('\n'),
      value: 'config/policy-v2.yaml',
      expected: 'file: config/policy-v2.yaml',
    },
    {
      tab: 'response',
      label: 'Include Reasoning Summary',
      initialYaml: [
        'name: insurance',
        'response:',
        '  include_reasoning_summary: true',
        '  include_review_results: true',
        '',
      ].join('\n'),
      value: 'false',
      expected: 'include_reasoning_summary: false',
    },
  ])('saves $tab configuration through the draft contract API', async ({ tab, label, initialYaml, value, expected }) => {
    mockContract = {
      ...mockContract,
      agent_yaml: initialYaml,
    }

    renderPage(`/agents/agent-1/drafts/draft-1?tab=${tab}`)

    fireEvent.change(screen.getByLabelText(label), {
      target: { value },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    expect(latestSavedAgentYaml()).toContain(expected)
  })

  it('saves Memory provider and scope settings through the draft contract API', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'memory:',
        '  provider: local',
        '  scopes:',
        '    case:',
        '      enabled: false',
        '      retention_days: 30',
        '      max_records: 5',
        '      allow_restricted: false',
        '    user:',
        '      enabled: false',
        '    shared:',
        '      enabled: false',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=memory')

    fireEvent.change(screen.getByLabelText('Memory Provider'), {
      target: { value: 'session' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Toggle Case Memory' }))
    fireEvent.change(screen.getByLabelText('Retention (Days)'), {
      target: { value: '45' },
    })
    fireEvent.change(screen.getByLabelText('Max Records'), {
      target: { value: '9' },
    })
    fireEvent.click(screen.getByLabelText('Allow Restricted'))

    expect(screen.queryByRole('button', { name: 'Save Workflow' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Memory' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain('provider: session')
    expect(savedYaml).toContain('enabled: true')
    expect(savedYaml).toContain('retention_days: 45')
    expect(savedYaml).toContain('max_records: 9')
    expect(savedYaml).toContain('allow_restricted: true')
  })

  it('saves unified Model settings across answer, planner, and reviewer roles', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'model:',
        '  provider: deepseek',
        '  name: deepseek-chat',
        '  credential_ref:',
        '    type: env',
        '    name: DEEPSEEK_API_KEY',
        '  params:',
        '    temperature: 0',
        '    max_output_tokens: 800',
        '    timeout_seconds: 20',
        'react:',
        '  max_steps: 6',
        '  max_tool_calls: 4',
        '  record_reasoning_summary: true',
        '  planner:',
        '    provider: deepseek',
        '    name: deepseek-chat',
        '    credential_ref:',
        '      type: env',
        '      name: DEEPSEEK_API_KEY',
        '    params:',
        '      temperature: 0',
        '      max_output_tokens: 800',
        '      timeout_seconds: 20',
        'review:',
        '  mode: rules_only',
        '  subagent:',
        '    provider: deepseek',
        '    name: deepseek-chat',
        '    credential_ref:',
        '      type: env',
        '      name: DEEPSEEK_API_KEY',
        '    fail_closed: true',
        '    params:',
        '      temperature: 0',
        '      max_output_tokens: 800',
        '      timeout_seconds: 20',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=model')
    expect(await screen.findByText('Model Configuration')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'openai' },
    })
    fireEvent.change(screen.getByLabelText('Model Name'), {
      target: { value: 'gpt-4.1-mini' },
    })
    fireEvent.change(screen.getByLabelText('Temperature'), {
      target: { value: '0.2' },
    })
    fireEvent.change(screen.getByLabelText('Max ReAct Steps'), {
      target: { value: '9' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Config' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain('model:\n  provider: openai\n  name: gpt-4.1-mini')
    expect(savedYaml).toContain('planner:\n    provider: openai\n    name: gpt-4.1-mini')
    expect(savedYaml).toContain('subagent:\n    provider: openai\n    name: gpt-4.1-mini')
    expect(savedYaml).toContain('temperature: 0.2')
    expect(savedYaml).toContain('max_steps: 9')
  })

  it('loads shared model connections for the Model module selector', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: `name: insurance
model:
  provider: deepseek
  name: deepseek-chat
react:
  planner:
    provider: deepseek
    name: deepseek-chat
review:
  subagent:
    provider: deepseek
    name: deepseek-chat
    fail_closed: true
`,
    }
    vi.mocked(fetchModelConnections).mockResolvedValue({
      data: [
        {
          connection_id: 'model_deepseek_default',
          display_name: 'DeepSeek Default',
          description: '',
          tags: [],
          provider: 'deepseek',
          model_identifier: 'deepseek-chat',
          base_url: 'https://api.deepseek.com',
          credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
          organization_env: null,
          project_env: null,
          timeout_seconds: 20,
          lifecycle_state: 'ACTIVE',
          created_at: '2026-06-07T00:00:00Z',
          updated_at: '2026-06-07T00:00:00Z',
          reference_summary: {
            connection_id: 'model_deepseek_default',
            draft_agent_reference_count: 0,
            published_agent_version_reference_count: 0,
            knowledge_source_reference_count: 0,
            in_flight_operation_count: 0,
            audit_retention_blocked: false,
          },
          last_validation: null,
          last_smoke_test: null,
        },
      ],
      meta: { total: 1 },
    })

    renderPage()
    fireEvent.click(screen.getByText('Model'))

    await waitFor(() => {
      expect(fetchModelConnections).toHaveBeenCalled()
    })
    expect(screen.getByRole('option', { name: 'DeepSeek Default' })).toBeInTheDocument()
  })
})
