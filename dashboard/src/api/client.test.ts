import { afterEach, expect, test, vi } from 'vitest'
import { fetchHandoffs } from './client'

afterEach(() => {
  vi.restoreAllMocks()
})

test('fetchHandoffs requests internal handoff projection', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  const response = await fetchHandoffs()

  expect(fetchMock).toHaveBeenCalledWith('/api/handoffs', undefined)
  expect(response.data).toEqual([])
})
