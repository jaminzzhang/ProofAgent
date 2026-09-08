// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useConfigDraft } from '../useConfigDraft'
import { fetchConfigDraft, fetchConfigDraftContract } from '../../api/client'
import type { DraftAgent, ContractBundle } from '../../api/types'
vi.mock('../../api/client', () => ({ fetchConfigDraft: vi.fn(), fetchConfigDraftContract: vi.fn() }))
beforeEach(() => vi.resetAllMocks())
it('keeps the selected Agent when an older request resolves last', async () => {
  let resolveOld!: (draft: DraftAgent) => void
  vi.mocked(fetchConfigDraft).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValue({ agent_id: 'new', revision: 2 } as DraftAgent)
  vi.mocked(fetchConfigDraftContract).mockResolvedValue({ agent_yaml: 'name: new' } as ContractBundle)
  const { result, rerender } = renderHook(({ id }) => useConfigDraft(id, 'draft'), { initialProps: { id: 'old' } })
  rerender({ id: 'new' })
  await waitFor(() => expect(result.current.draft?.agent_id).toBe('new'))
  await act(async () => resolveOld({ agent_id: 'old' } as DraftAgent))
  expect(result.current.draft?.agent_id).toBe('new')
})

it('retries a torn revision/contract read instead of allowing old content with a new revision', async () => {
  vi.mocked(fetchConfigDraft)
    .mockResolvedValueOnce({ agent_id: 'new', revision: 1 } as DraftAgent)
    .mockResolvedValue({ agent_id: 'new', revision: 2 } as DraftAgent)
  vi.mocked(fetchConfigDraftContract)
    .mockResolvedValueOnce({ agent_yaml: 'purpose: old' } as ContractBundle)
    .mockResolvedValue({ agent_yaml: 'purpose: new' } as ContractBundle)
  const { result } = renderHook(() => useConfigDraft('new', 'draft'))
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.draft?.revision).toBe(2)
  expect(result.current.contract?.agent_yaml).toBe('purpose: new')
})

it('fails visibly without an editable snapshot when the revision never stabilizes', async () => {
  let revision = 0
  vi.mocked(fetchConfigDraft).mockImplementation(async () => ({ revision: ++revision } as DraftAgent))
  vi.mocked(fetchConfigDraftContract).mockResolvedValue({ agent_yaml: 'purpose: racing' } as ContractBundle)
  const { result } = renderHook(() => useConfigDraft('new', 'draft'))
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.error).toBe('agent_draft_snapshot_changed_retry')
  expect(result.current.draft).toBeNull()
  expect(result.current.contract).toBeNull()
})
