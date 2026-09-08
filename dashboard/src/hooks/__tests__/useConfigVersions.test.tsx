// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useConfigVersions } from '../useConfigVersions'
import { fetchConfigVersions } from '../../api/client'
import type { ConfigVersionsResponse } from '../../api/types'
vi.mock('../../api/client', () => ({ fetchConfigVersions: vi.fn() }))
it('does not replace the selected Agent active version with a delayed previous Agent response', async () => {
  let resolveOld!: (value: ConfigVersionsResponse) => void
  vi.mocked(fetchConfigVersions).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValueOnce({ data: [], meta: { total: 0, active_version_id: 'new-version' } })
  const { result, rerender } = renderHook(({ id }) => useConfigVersions(id), { initialProps: { id: 'old' } })
  rerender({ id: 'new' })
  await waitFor(() => expect(result.current.activeVersionId).toBe('new-version'))
  await act(async () => resolveOld({ data: [], meta: { total: 0, active_version_id: 'old-version' } }))
  expect(result.current.activeVersionId).toBe('new-version')
})
