// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bindKnowledgeSourceToDraft,
  createModelConnection,
  fetchKnowledgeSources,
  fetchModelConnections,
  validateConfigDraft,
} from '../../api/client'
import type { DraftValidationResponse } from '../../api/types'
import { AgentDetailPage } from '../AgentDetailPage'

vi.mock('../../api/client', () => ({
  bindKnowledgeSourceToDraft: vi.fn(),
  chatUrl: (path: string) => `http://localhost:5174${path}`,
  createModelConnection: vi.fn(),
  fetchKnowledgeSources: vi.fn(),
  fetchModelConnections: vi.fn(),
  publishConfigDraft: vi.fn(),
  rollbackConfigVersion: vi.fn(),
  updateConfigDraft: vi.fn(),
  updateConfigDraftContract: vi.fn(),
  validateConfigDraft: vi.fn(),
}))

const refreshDraft = vi.fn()
const refreshVersions = vi.fn()
let mockDraft = {
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
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/agents/:agentId/drafts/:draftId" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AgentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchModelConnections).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createModelConnection).mockRejectedValue(new Error('not mocked'))
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

  it('shows validation busy state while a quick test is running', async () => {
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
    fireEvent.click(screen.getByRole('button', { name: 'Run Test' }))

    expect(screen.getByRole('button', { name: 'Running...' })).toBeDisabled()

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

  it('restores the Validate & Test module from the route query', () => {
    renderPage('/agents/agent-1/drafts/draft-1?tab=validate')

    expect(screen.getByPlaceholderText('Enter a test question...')).toBeInTheDocument()
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

    renderPage()
    fireEvent.click(screen.getByText('Versions'))

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
        actor: 'dashboard',
      })
    })
    expect(refreshDraft).toHaveBeenCalled()
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
