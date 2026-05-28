// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { validateConfigDraft } from '../../api/client'
import type { DraftValidationResponse } from '../../api/types'
import { AgentDetailPage } from '../AgentDetailPage'

vi.mock('../../api/client', () => ({
  publishConfigDraft: vi.fn(),
  rollbackConfigVersion: vi.fn(),
  updateConfigDraft: vi.fn(),
  updateConfigDraftContract: vi.fn(),
  validateConfigDraft: vi.fn(),
}))

const refreshDraft = vi.fn()
const refreshVersions = vi.fn()

vi.mock('../../hooks/useConfigDraft', () => ({
  useConfigDraft: () => ({
    draft: {
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
    },
    contract: {
      agent_yaml: 'name: insurance\nmemory:\n  provider: local\n',
      policy_yaml: '',
      tools_yaml: '',
      extra_files: {},
      advanced_fields: {},
    },
    loading: false,
    error: null,
    refresh: refreshDraft,
  }),
}))

vi.mock('../../hooks/useConfigVersions', () => ({
  useConfigVersions: () => ({
    versions: [],
    activeVersionId: null,
    loading: false,
    error: null,
    refresh: refreshVersions,
  }),
}))

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/agents/agent-1/drafts/draft-1']}>
      <Routes>
        <Route path="/agents/:agentId/drafts/:draftId" element={<AgentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AgentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
