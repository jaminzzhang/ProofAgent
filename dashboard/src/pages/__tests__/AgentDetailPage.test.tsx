// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '@proofagent/ui'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bindKnowledgeSourceToDraft,
  createModelConnection,
  fetchConfigDraftSkills,
  fetchRunDetail,
  fetchValidationCapture,
  fetchRuns,
  fetchWorkflowTemplate,
  fetchKnowledgeSources,
  fetchModelConnections,
  previewWorkflowStageContext,
  createConfigDraftSkillPack,
  deleteConfigDraftSkillPack,
  updateConfigDraft,
  updateConfigDraftSkillPack,
  updateConfigDraftContract,
  updateWorkflowStages,
  validateConfigDraft,
} from '../../api/client'
import type { DraftAgent, DraftValidationResponse, RunDetail } from '../../api/types'
import { LocaleProvider } from '../../i18n/locale'
import { AgentDetailPage } from '../AgentDetailPage'

vi.mock('../../api/client', () => ({
  bindKnowledgeSourceToDraft: vi.fn(),
  chatUrl: (path: string) => `http://localhost:5174${path}`,
  createModelConnection: vi.fn(),
  createConfigDraftSkillPack: vi.fn(),
  deleteConfigDraftSkillPack: vi.fn(),
  fetchConfigDraftSkills: vi.fn(),
  fetchRunDetail: vi.fn(),
  fetchRuns: vi.fn(),
  fetchValidationCapture: vi.fn(),
  fetchWorkflowTemplate: vi.fn(),
  // useWorkflowTemplates (consumed by WorkflowModuleEditor) fetches the catalog
  // once and caches it module-side. Return the full registry so the catalog
  // lookup in saveStages can resolve any selected template's descriptor_version.
  fetchWorkflowTemplates: vi.fn().mockResolvedValue({
    data: [
      { name: 'enterprise_qa', description: 'Legacy.', descriptor_version: 'enterprise_qa.v1', stages: [] },
      { name: 'react_enterprise_qa', description: 'React v1.', descriptor_version: 'react_enterprise_qa.v1', stages: [] },
      { name: 'react_enterprise_qa_v2', description: 'React v2.', descriptor_version: 'react_enterprise_qa.v2', stages: [] },
      { name: 'react_enterprise_qa_v3', description: 'React v3 loop.', descriptor_version: 'react_enterprise_qa.v3', stages: [] },
    ],
    meta: { total: 4 },
  }),  fetchKnowledgeSources: vi.fn(),
  fetchModelConnections: vi.fn(),
  previewWorkflowStageContext: vi.fn(),
  publishConfigDraft: vi.fn(),
  rollbackConfigVersion: vi.fn(),
  unbindKnowledgeSourceFromDraft: vi.fn(),
  updateConfigDraft: vi.fn(),
  updateConfigDraftSkillPack: vi.fn(),
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
let testStorage: Record<string, string> = {}

function installTestLocalStorage() {
  testStorage = {}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => testStorage[key] ?? null,
    setItem: (key: string, value: string) => {
      testStorage[key] = value
    },
    removeItem: (key: string) => {
      delete testStorage[key]
    },
    clear: () => {
      testStorage = {}
    },
    key: (index: number) => Object.keys(testStorage)[index] ?? null,
    get length() {
      return Object.keys(testStorage).length
    },
  })
}

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
    <ThemeProvider>
      <LocaleProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/agents/:agentId/drafts/:draftId" element={<AgentDetailPage />} />
          </Routes>
        </MemoryRouter>
      </LocaleProvider>
    </ThemeProvider>,
  )
}

function latestSavedAgentYaml(): string {
  const payload = vi.mocked(updateConfigDraftContract).mock.calls.at(-1)?.[2]
  if (!payload?.agent_yaml) throw new Error('No agent_yaml payload was saved.')
  return payload.agent_yaml
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 'run-1',
    question: 'What documents are required?',
    outcome: 'ANSWERED_WITH_CITATIONS',
    run_purpose: 'validation',
    agent_id: 'agent-1',
    agent_version_id: null,
    draft_id: 'draft-1',
    created_at: '2026-05-28T01:00:00Z',
    updated_at: '2026-05-28T01:00:00Z',
    approval_status: null,
    error_code: null,
    trace_events: [],
    receipt_markdown: '# Receipt',
    evidence_chunks: [],
    policy_decisions: [],
    model_usage: {},
    approval_state: null,
    pending_approvals: [],
    governance_details: {},
    workflow_projection: {
      template_name: null,
      template_descriptor_version: null,
      stage_configuration_source: {},
      stages: [],
    },
    ...overrides,
  }
}

function skillPackArticle(label: string): HTMLElement {
  const article = screen.getByRole('heading', { name: label }).closest('article')
  if (!article) throw new Error(`Skill Pack row not found: ${label}`)
  return article
}

/**
 * Add a value to a ReferenceChips control. The chip input is labelled
 * "Add to {fieldLabel}"; typing + Enter commits it.
 */
function addReferenceChip(
  scope: ReturnType<typeof within>,
  fieldLabel: string,
  value: string,
) {
  const input = scope.getByLabelText(`Add to ${fieldLabel}`)
  fireEvent.change(input, { target: { value } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

describe('AgentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    installTestLocalStorage()
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchModelConnections).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchConfigDraftSkills).mockResolvedValue({
      enabled: true,
      template_name: 'react_enterprise_qa_v2',
      template_descriptor_version: 'react_enterprise_qa.v2',
      addendum_slots: [
        { stage_id: 'plan', stage_label: 'Plan' },
        { stage_id: 'retrieval_review', stage_label: 'Retrieval Review' },
        { stage_id: 'tool_review', stage_label: 'Tool Review' },
        { stage_id: 'model_answer', stage_label: 'Model Answer' },
      ],
      packs: [
        {
          id: 'claims_qa',
          label: 'Claims QA',
          description: 'Claim handling guidance.',
          definition: 'skills/claims.yaml',
          default: true,
          routing_admission: {
            intent_patterns: ['claim status'],
            intent_taxonomy_refs: [],
            admission: { min_confidence: 0.6 },
            routing_safe_summary: {
              id: 'claims_qa',
              label: 'Claims QA',
              default: true,
              admission: { min_confidence: 0.6 },
            },
          },
          capability_refs: {
            knowledge_binding_refs: ['kb_local'],
            tool_contract_refs: [],
            policy_rule_refs: ['answering.require_retrieval'],
            validator_refs: [],
          },
          stage_addenda: [
            {
              stage_id: 'plan',
              stage_label: 'Plan',
              configured: true,
              prompt: {
                business_context: 'Claims stage context.',
                task_instructions: ['Prefer retrieval.'],
                output_preferences: [],
              },
              preview: {
                merge_mode: 'append',
                business_context: 'Base plan context.\n\nClaims stage context.',
                task_instructions: ['Use governed planning.', 'Prefer retrieval.'],
                output_preferences: [],
              },
            },
            {
              stage_id: 'retrieval_review',
              stage_label: 'Retrieval Review',
              configured: false,
              prompt: { business_context: '', task_instructions: [], output_preferences: [] },
              preview: {
                merge_mode: 'append',
                business_context: '',
                task_instructions: [],
                output_preferences: [],
              },
            },
            {
              stage_id: 'tool_review',
              stage_label: 'Tool Review',
              configured: false,
              prompt: { business_context: '', task_instructions: [], output_preferences: [] },
              preview: {
                merge_mode: 'append',
                business_context: '',
                task_instructions: [],
                output_preferences: [],
              },
            },
            {
              stage_id: 'model_answer',
              stage_label: 'Model Answer',
              configured: false,
              prompt: { business_context: '', task_instructions: [], output_preferences: [] },
              preview: {
                merge_mode: 'append',
                business_context: '',
                task_instructions: [],
                output_preferences: [],
              },
            },
          ],
          coverage: {
            configured_stage_ids: ['plan'],
            missing_stage_ids: ['retrieval_review', 'tool_review', 'model_answer'],
          },
        },
      ],
    })
    vi.mocked(createConfigDraftSkillPack).mockImplementation(async () =>
      vi.mocked(fetchConfigDraftSkills).getMockImplementation()?.('agent-1', 'draft-1') as never,
    )
    vi.mocked(updateConfigDraftSkillPack).mockImplementation(async () =>
      vi.mocked(fetchConfigDraftSkills).getMockImplementation()?.('agent-1', 'draft-1') as never,
    )
    vi.mocked(deleteConfigDraftSkillPack).mockImplementation(async () =>
      vi.mocked(fetchConfigDraftSkills).getMockImplementation()?.('agent-1', 'draft-1') as never,
    )
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
    vi.mocked(fetchRunDetail).mockResolvedValue(runDetail({
      run_id: 'run-production-1',
      question: 'What documents are required?',
      run_purpose: 'production',
      agent_version_id: 'version-1',
      draft_id: null,
    }))
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

  it('opens Agent run detail in a right-side drawer without leaving Agent detail', async () => {
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /What documents are required/ }))

    const drawer = await screen.findByRole('dialog', { name: 'Run detail' })
    expect(fetchRunDetail).toHaveBeenCalledWith('run-production-1')
    expect(within(drawer).getByText('run-production-1')).toBeInTheDocument()
    expect(within(drawer).getByText('Governance Receipt')).toBeInTheDocument()
    expect(screen.getByText('Agent Overview')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Back to Runs/ })).not.toBeInTheDocument()
  })

  it('renders Agent Detail shell and overview in Chinese when locale is zh-CN', async () => {
    globalThis.localStorage.setItem('proof-agent-locale', 'zh-CN')
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

    expect(screen.getByRole('navigation', { name: 'Agent 导航' })).toBeInTheDocument()
    expect(screen.getByText('设计')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '概览' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('Agent 概览')).toBeInTheDocument()
    expect(screen.getByLabelText('显示名称')).toHaveValue('Insurance Agent')
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument()
    expect(await screen.findByText('生产 Runs')).toBeInTheDocument()
    expect(screen.getByText('近期 Agent Runs')).toBeInTheDocument()
    expect(screen.queryByText('Agent Overview')).not.toBeInTheDocument()
    expect(screen.queryByText('Production Runs')).not.toBeInTheDocument()
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

  it('blocks validation when gated Persistent User Memory is enabled', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'capabilities:',
        '  memory:',
        '    enabled: true',
        '    provider: local',
        '    scopes:',
        '      case:',
        '        enabled: true',
        '      user:',
        '        enabled: true',
        '      shared:',
        '        enabled: false',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByText(/Persistent User Memory requires subject identity, consent policy, and lifecycle controls/)).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Enter a test question...'), {
      target: { value: 'What documents are required?' },
    })
    expect(screen.getByRole('button', { name: 'Run Validation' })).toBeDisabled()
    expect(validateConfigDraft).not.toHaveBeenCalled()
  })

  it('blocks validation when context-only Persistent User Memory recall is enabled', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'context:',
        '  source_policies:',
        '    memory_recall:',
        '      scopes:',
        '        user:',
        '          enabled: true',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByText(/Persistent User Memory requires subject identity, consent policy, and lifecycle controls/)).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Enter a test question...'), {
      target: { value: 'What documents are required?' },
    })
    expect(screen.getByRole('button', { name: 'Run Validation' })).toBeDisabled()
    expect(validateConfigDraft).not.toHaveBeenCalled()
  })

  it('blocks validation when context-only Shared Memory recall is enabled', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'context:',
        '  source_policies:',
        '    memory_recall:',
        '      scopes:',
        '        shared:',
        '          enabled: true',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByText(/Shared Memory is unavailable until cross-user governance is defined/)).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('Enter a test question...'), {
      target: { value: 'What documents are required?' },
    })
    expect(screen.getByRole('button', { name: 'Run Validation' })).toBeDisabled()
    expect(validateConfigDraft).not.toHaveBeenCalled()
  })

  it('blocks publication when gated Persistent User Memory is enabled', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'capabilities:',
        '  memory:',
        '    enabled: true',
        '    provider: local',
        '    scopes:',
        '      case:',
        '        enabled: true',
        '      user:',
        '        enabled: true',
        '      shared:',
        '        enabled: false',
        '',
      ].join('\n'),
    }
    mockDraft = {
      ...mockDraft,
      validation_records: [
        {
          validation_id: 'validation-1',
          run_id: 'run-validation-1',
          status: 'completed',
          draft_id: 'draft-1',
          created_at: '2026-05-28T01:00:00Z',
          errors: [],
          summary: 'Ready.',
          validation_capture_id: null,
        },
      ],
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=versions')

    expect(screen.getByText(/Persistent User Memory requires subject identity, consent policy, and lifecycle controls/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
  })

  it('blocks publication when context-only Shared Memory recall is enabled', () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'context:',
        '  source_policies:',
        '    memory_recall:',
        '      scopes:',
        '        shared:',
        '          enabled: true',
        '',
      ].join('\n'),
    }
    mockDraft = {
      ...mockDraft,
      validation_records: [
        {
          validation_id: 'validation-1',
          run_id: 'run-validation-1',
          status: 'completed',
          draft_id: 'draft-1',
          created_at: '2026-05-28T01:00:00Z',
          errors: [],
          summary: 'Ready.',
          validation_capture_id: null,
        },
      ],
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=versions')

    expect(screen.getByText(/Shared Memory is unavailable until cross-user governance is defined/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
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
    expect(screen.getByText('LLM Input/Output')).toBeInTheDocument()
    expect(screen.getByText('react_planner')).toBeInTheDocument()
    // The message view renders each request message verbatim and the response as
    // a formatted JSON block (see ADR-0044).
    expect(screen.getByText('{"question":"Q"}')).toBeInTheDocument()
    expect(screen.getByText(/"action_type": "plan_retrieval"/)).toBeInTheDocument()
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
    expect(screen.getByText('Relationship Map')).toBeInTheDocument()
    expect(screen.getAllByText('Plan').length).toBeGreaterThan(0)
    // Field help is rendered via the shared Tooltip primitive (opens on focus).
    fireEvent.focus(await screen.findByRole('button', { name: 'Explain Business Context' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/Adds domain-specific context/)
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

  it('persists the Workflow core before saving stages when the template changed', async () => {
    // Regression: switching the Template dropdown to react_enterprise_qa_v3 and
    // clicking Save Stages previously sent template_descriptor_version=v3 while
    // the server-side template was still v1 (core not persisted), causing a
    // 400 "template_descriptor_version does not match registered template".
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

    vi.mocked(updateConfigDraftContract).mockResolvedValue({
      agent_yaml: `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v3
  checkpointer:
    type: memory
`,
      policy_yaml: '',
      tools_yaml: '',
      extra_files: {},
      advanced_fields: {},
    })
    vi.mocked(updateWorkflowStages).mockResolvedValue({
      agent_yaml: `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v3
  checkpointer:
    type: memory
`,
      policy_yaml: '',
      tools_yaml: '',
      extra_files: {},
      advanced_fields: {},
    })

    const templateSelect = await screen.findByLabelText('Template')
    fireEvent.change(templateSelect, { target: { value: 'react_enterprise_qa_v3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    // The core contract must be persisted first so the server-side template
    // matches the descriptor_version sent with the stages.
    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalledWith('agent-1', 'draft-1', expect.objectContaining({
        agent_yaml: expect.stringContaining('template: react_enterprise_qa_v3'),
      }))
    })
    await waitFor(() => {
      expect(updateWorkflowStages).toHaveBeenCalledWith('agent-1', 'draft-1', expect.objectContaining({
        template_descriptor_version: 'react_enterprise_qa.v3',
      }))
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

  it('keeps Workflow core template_descriptor_version aligned when changing templates', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
  template_descriptor_version: react_enterprise_qa.v2
  checkpointer:
    provider: sqlite
    uri: sqlite:///runs/config/checkpoints.db
`,
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=workflow')

    const templateSelect = await screen.findByLabelText('Template')
    fireEvent.change(templateSelect, { target: { value: 'react_enterprise_qa_v3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Core' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalledWith('agent-1', 'draft-1', expect.objectContaining({
        agent_yaml: expect.stringContaining('template: react_enterprise_qa_v3'),
      }))
    })
    expect(latestSavedAgentYaml()).toContain('template_descriptor_version: react_enterprise_qa.v3')
    expect(latestSavedAgentYaml()).not.toContain('template_descriptor_version: react_enterprise_qa.v2')
  })

  it('renders Business Flow Skill Packs as the default Skills list view', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    expect(await screen.findByText('Skills Configuration')).toBeInTheDocument()
    expect(fetchConfigDraftSkills).toHaveBeenCalledWith('agent-1', 'draft-1')
    expect(screen.getByText('Business Flow Skill Packs')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New Skill Pack' })).toBeInTheDocument()
    expect(screen.getByText('Claims QA')).toBeInTheDocument()
    expect(screen.getByText('claims_qa')).toBeInTheDocument()
    expect(screen.getByText('skills/claims.yaml')).toBeInTheDocument()
    expect(screen.getByText('Default')).toBeInTheDocument()
    expect(screen.getByText('claim status')).toBeInTheDocument()
    expect(screen.getByText('1/4 stages configured')).toBeInTheDocument()
    expect(screen.getByText('1 knowledge / 0 tools / 1 policy / 0 validators')).toBeInTheDocument()
    expect(screen.getByText('min confidence 0.6')).toBeInTheDocument()
    const claimsRow = skillPackArticle('Claims QA')
    expect(within(claimsRow).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(within(claimsRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(screen.queryByText('Routing & Admission')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('Claims stage context.')).not.toBeInTheDocument()
  })

  it('shows available Skill Pack addendum slots before any pack exists', async () => {
    vi.mocked(fetchConfigDraftSkills).mockResolvedValueOnce({
      enabled: false,
      template_name: 'react_enterprise_qa_v2',
      template_descriptor_version: 'react_enterprise_qa.v2',
      addendum_slots: [
        { stage_id: 'plan', stage_label: 'Plan' },
        { stage_id: 'retrieval_review', stage_label: 'Retrieval Review' },
        { stage_id: 'tool_review', stage_label: 'Tool Review' },
        { stage_id: 'model_answer', stage_label: 'Model Answer' },
      ],
      packs: [],
    })

    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    expect(await screen.findByText('Business Flow Skill Packs')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New Skill Pack' })).toBeInTheDocument()
    expect(screen.getByText('No Business Flow Skill Packs configured.')).toBeInTheDocument()
    expect(screen.getByText('Available Addendum Slots')).toBeInTheDocument()
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('Retrieval Review')).toBeInTheDocument()
    expect(screen.getByText('Tool Review')).toBeInTheDocument()
    expect(screen.getByText('Model Answer')).toBeInTheDocument()
  })

  it('opens new Skill Pack creation in a right-side drawer', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    expect(await screen.findByText('Business Flow Skill Packs')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'New Skill Pack' }))

    const drawer = screen.getByRole('dialog', { name: 'Create Business Flow Skill Pack' })
    expect(within(drawer).getByText('Basics')).toBeInTheDocument()
    expect(within(drawer).getByLabelText('Pack ID')).toBeInTheDocument()
    expect(within(drawer).getByLabelText('Label')).toBeInTheDocument()
    expect(within(drawer).getByText('Routing')).toBeInTheDocument()
    expect(within(drawer).getByLabelText('Intent Patterns')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Capability References' }))
    expect(within(drawer).getByLabelText('Knowledge Bindings')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addenda' }))
    expect(within(drawer).getByLabelText('Plan Business Context')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Preview' })).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Create Skill Pack' })).toBeDisabled()
    expect(screen.getByText('Claims QA')).toBeInTheDocument()
  })

  it('keeps advanced new Skill Pack sections collapsed until selected', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    fireEvent.click(await screen.findByRole('button', { name: 'New Skill Pack' }))
    const drawer = screen.getByRole('dialog', { name: 'Create Business Flow Skill Pack' })
    const capabilitySection = within(drawer).getByRole('button', { name: 'Capability References' })

    expect(capabilitySection).toHaveAttribute('aria-expanded', 'false')
    expect(within(drawer).queryByLabelText('Knowledge Bindings')).not.toBeInTheDocument()

    fireEvent.click(capabilitySection)

    expect(capabilitySection).toHaveAttribute('aria-expanded', 'true')
    expect(within(drawer).getByLabelText('Knowledge Bindings')).toBeInTheDocument()
  })

  it('previews a new Skill Pack deterministically before saving it', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    fireEvent.click(await screen.findByRole('button', { name: 'New Skill Pack' }))
    const drawer = screen.getByRole('dialog', { name: 'Create Business Flow Skill Pack' })
    fireEvent.change(within(drawer).getByLabelText('Pack ID'), { target: { value: 'appeals_qa' } })
    fireEvent.change(within(drawer).getByLabelText('Label'), { target: { value: 'Appeals QA' } })
    fireEvent.change(within(drawer).getByLabelText('Intent Patterns'), {
      target: { value: 'appeal status\nappeal escalation' },
    })
    fireEvent.change(within(drawer).getByLabelText('Minimum Confidence'), { target: { value: '0.75' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Capability References' }))
    addReferenceChip(within(drawer), 'Knowledge Bindings', 'kb_appeals')
    addReferenceChip(within(drawer), 'Policy Rules', 'answering.require_retrieval')
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addenda' }))
    fireEvent.change(within(drawer).getByLabelText('Plan Business Context'), {
      target: { value: 'Appeals stage context.' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Preview' }))

    expect(within(drawer).getByText('Routing-Safe Preview')).toBeInTheDocument()
    expect(within(drawer).getByText('appeals_qa')).toBeInTheDocument()
    expect(within(drawer).getByText('Appeals QA')).toBeInTheDocument()
    expect(within(drawer).getByText('2 intent patterns')).toBeInTheDocument()
    expect(within(drawer).getByText('min confidence 0.75')).toBeInTheDocument()
    expect(within(drawer).getByText('1 knowledge / 0 tools / 1 policy / 0 validators')).toBeInTheDocument()
    expect(within(drawer).getByText('Affected Addendum Slots')).toBeInTheDocument()
    expect(within(drawer).getAllByText('Plan').length).toBeGreaterThan(0)
    expect(within(drawer).getByText('append-only addendum configured')).toBeInTheDocument()
    expect(createConfigDraftSkillPack).not.toHaveBeenCalled()
    expect(updateConfigDraftSkillPack).not.toHaveBeenCalled()
  })

  it('opens existing Skill Pack configuration in a right-side drawer', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    await screen.findByText('Business Flow Skill Packs')
    fireEvent.click(within(skillPackArticle('Claims QA')).getByRole('button', { name: 'Edit' }))

    const drawer = screen.getByRole('dialog', { name: 'Edit Business Flow Skill Pack' })
    expect(within(drawer).getByText('Basics')).toBeInTheDocument()
    expect(within(drawer).getByDisplayValue('Claims QA')).toBeInTheDocument()
    expect(within(drawer).getByText('Routing & Admission')).toBeInTheDocument()
    expect(within(drawer).getByDisplayValue('claim status')).toBeInTheDocument()
    expect(within(drawer).getByText('Routing-Safe Summary')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Capability References' }))
    expect(within(drawer).getByText('kb_local')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addendum Slots' }))
    expect(within(drawer).getByDisplayValue('Claims stage context.')).toBeInTheDocument()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Prompt Preview' }))
    expect(within(drawer).getByText('Prompt Preview')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Save Skill Pack' })).toBeInTheDocument()
    expect(screen.getByText('Business Flow Skill Packs')).toBeInTheDocument()
  })

  it('previews unsaved Skill Pack addendum edits before saving them', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    await screen.findByText('Business Flow Skill Packs')
    fireEvent.click(within(skillPackArticle('Claims QA')).getByRole('button', { name: 'Edit' }))
    const drawer = screen.getByRole('dialog', { name: 'Edit Business Flow Skill Pack' })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addendum Slots' }))
    fireEvent.change(within(drawer).getByLabelText('Plan Business Context'), {
      target: { value: 'Updated claims context.' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addendum Slots' }))
    fireEvent.click(within(drawer).getByRole('button', { name: 'Prompt Preview' }))

    expect(within(drawer).getByText(/Base plan context\./)).toBeInTheDocument()
    expect(within(drawer).getByText(/Updated claims context\./)).toBeInTheDocument()
    expect(within(drawer).queryByText(/Claims stage context\./)).not.toBeInTheDocument()
    expect(updateConfigDraftSkillPack).not.toHaveBeenCalled()
  })

  it('creates a Skill Pack with complete drawer configuration', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    fireEvent.click(await screen.findByRole('button', { name: 'New Skill Pack' }))
    const drawer = screen.getByRole('dialog', { name: 'Create Business Flow Skill Pack' })
    fireEvent.change(within(drawer).getByLabelText('Pack ID'), { target: { value: 'appeals_qa' } })
    fireEvent.change(within(drawer).getByLabelText('Label'), { target: { value: 'Appeals QA' } })
    fireEvent.change(within(drawer).getByLabelText('Intent Patterns'), { target: { value: 'appeal status' } })
    fireEvent.change(within(drawer).getByLabelText('Minimum Confidence'), { target: { value: '0.75' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Capability References' }))
    addReferenceChip(within(drawer), 'Knowledge Bindings', 'kb_appeals')
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addenda' }))
    fireEvent.change(within(drawer).getByLabelText('Plan Business Context'), { target: { value: 'Appeals stage context.' } })

    fireEvent.click(within(drawer).getByRole('button', { name: 'Create Skill Pack' }))

    await waitFor(() => {
      expect(createConfigDraftSkillPack).toHaveBeenCalledWith('agent-1', 'draft-1', {
        id: 'appeals_qa',
        label: 'Appeals QA',
        description: '',
        intent_patterns: ['appeal status'],
        intent_taxonomy_refs: [],
        default: false,
      })
    })
    expect(updateConfigDraftSkillPack).toHaveBeenCalledWith('agent-1', 'draft-1', 'appeals_qa', expect.objectContaining({
      admission: { min_confidence: 0.75 },
      knowledge_binding_refs: ['kb_appeals'],
      stage_prompt_addenda: {
        plan: {
          business_context: 'Appeals stage context.',
          task_instructions: [],
          output_preferences: [],
        },
      },
    }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Create Business Flow Skill Pack' })).not.toBeInTheDocument()
    })
  })

  it('saves existing Skill Pack edits from the drawer', async () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=skills')

    await screen.findByText('Business Flow Skill Packs')
    fireEvent.click(within(skillPackArticle('Claims QA')).getByRole('button', { name: 'Edit' }))
    const drawer = screen.getByRole('dialog', { name: 'Edit Business Flow Skill Pack' })
    fireEvent.change(within(drawer).getByLabelText('Minimum Confidence'), { target: { value: '0.8' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Stage Addendum Slots' }))
    fireEvent.change(within(drawer).getByLabelText('Plan Business Context'), { target: { value: 'Updated claims context.' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'Save Skill Pack' }))

    await waitFor(() => {
      expect(updateConfigDraftSkillPack).toHaveBeenCalledWith('agent-1', 'draft-1', 'claims_qa', expect.objectContaining({
        admission: { min_confidence: 0.8 },
        stage_prompt_addenda: expect.objectContaining({
          plan: expect.objectContaining({ business_context: 'Updated claims context.' }),
        }),
      }))
    })
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

    fireEvent.change(screen.getByDisplayValue('3'), {
      target: { value: '8' },
    })
    fireEvent.change(screen.getByDisplayValue('single_step'), {
      target: { value: 'agentic' },
    })

    expect(screen.queryByRole('button', { name: 'Save Workflow' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Knowledge' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain('strategy: agentic')
    expect(savedYaml).toContain('top_k: 8')
    expect(savedYaml).toContain('max_steps: 3')
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
      control: 'switch',
      expected: 'include_reasoning_summary: false',
    },
  ])('saves $tab configuration through the draft contract API', async ({ tab, label, initialYaml, value, control, expected }) => {
    mockContract = {
      ...mockContract,
      agent_yaml: initialYaml,
    }

    renderPage(`/agents/agent-1/drafts/draft-1?tab=${tab}`)

    if (control === 'switch') {
      // Booleans render as a Switch (role="switch"). Clicking toggles the value.
      fireEvent.click(screen.getByRole('switch', { name: label }))
    } else {
      fireEvent.change(screen.getByLabelText(label), {
        target: { value },
      })
    }
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
        'capabilities:',
        '  memory:',
        '    enabled: true',
        '    provider: local',
        '    scopes:',
        '      case:',
        '        enabled: false',
        '        retention_days: 30',
        '        max_records: 5',
        '        allow_restricted: false',
        '      user:',
        '        enabled: false',
        '      shared:',
        '        enabled: false',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=memory')

    fireEvent.change(screen.getByLabelText('Memory Provider'), {
      target: { value: 'session' },
    })
    fireEvent.click(screen.getByRole('switch', { name: 'Toggle Case Memory' }))
    fireEvent.change(screen.getByLabelText('Retention (Days)'), {
      target: { value: '45' },
    })
    fireEvent.change(screen.getByLabelText('Max Records'), {
      target: { value: '9' },
    })
    fireEvent.click(screen.getByRole('switch', { name: 'Allow Restricted' }))

    expect(screen.queryByRole('button', { name: 'Save Workflow' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Memory' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain(`capabilities:
  memory:
    enabled: true
    provider: session
    scopes:
      case:
        enabled: true
        retention_days: 45
        max_records: 9
        allow_restricted: true
      user:
        enabled: false
      shared:
        enabled: false`)
    expect(savedYaml).not.toContain('\nmemory:\n')
    expect(savedYaml).not.toContain('\ncontext:\n')
  })

  it('cuts legacy top-level memory over to canonical capabilities when saving Memory settings', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'memory:',
        '  provider: local',
        'policy:',
        '  file: ./policy.yaml',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=memory')

    fireEvent.change(screen.getByLabelText('Memory Provider'), {
      target: { value: 'mem0' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Memory' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain(`capabilities:
  memory:
    enabled: true
    provider: mem0
    scopes:
      case:
        enabled: false
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false`)
    expect(savedYaml).not.toContain('\nmemory:\n')
    expect(savedYaml).toContain(`policy:
  file: ./policy.yaml`)
  })

  it('does not persist an explicit budget profile when saving Memory Recall Admission only', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'capabilities:',
        '  memory:',
        '    enabled: true',
        '    provider: local',
        '    scopes:',
        '      case:',
        '        enabled: true',
        '        retention_days: 30',
        '        max_records: 5',
        '        allow_restricted: false',
        '      user:',
        '        enabled: false',
        '      shared:',
        '        enabled: false',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=memory')

    fireEvent.click(screen.getByRole('switch', { name: 'Toggle Case Memory Recall' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save Memory' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain(`context:
  source_policies:
    memory_recall:
      scopes:
        case:
          enabled: false
        user:
          enabled: false
        shared:
          enabled: false`)
    expect(savedYaml).not.toContain('budget_profile:')
  })

  it('writes complete explicit context configuration after a memory budget override', async () => {
    mockContract = {
      ...mockContract,
      agent_yaml: [
        'name: insurance',
        'capabilities:',
        '  memory:',
        '    enabled: true',
        '    provider: local',
        '    scopes:',
        '      case:',
        '        enabled: true',
        '        retention_days: 30',
        '        max_records: 5',
        '        allow_restricted: false',
        '      user:',
        '        enabled: false',
        '      shared:',
        '        enabled: false',
        '',
      ].join('\n'),
    }

    renderPage('/agents/agent-1/drafts/draft-1?tab=memory')

    expect(screen.getAllByPlaceholderText('Runtime dynamic default')).toHaveLength(2)
    fireEvent.change(screen.getByLabelText('Max Tokens'), {
      target: { value: '4096' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Memory' }))

    await waitFor(() => {
      expect(updateConfigDraftContract).toHaveBeenCalled()
    })
    const savedYaml = latestSavedAgentYaml()
    expect(savedYaml).toContain(`context:
  source_policies:
    memory_recall:
      scopes:
        case:
          enabled: true
        user:
          enabled: false
        shared:
          enabled: false
  budget_profile:
    max_tokens: 4096
    reserved_output_tokens: 0
    estimation_strategy: heuristic
    profile_version: context_budget.v1
  convergence:
    level1_ratio: 0.5
    level2_ratio: 0.8
    hard_limit_ratio: 1.0
  dynamic_calibration: true`)
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
