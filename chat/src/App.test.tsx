// @vitest-environment jsdom

import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import App from './App'

const storage: Storage = {
  length: 0,
  clear: vi.fn(),
  getItem: vi.fn(() => null),
  key: vi.fn(() => null),
  removeItem: vi.fn(),
  setItem: vi.fn(),
}

Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: storage,
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.pushState({}, '', '/')
})

test('customer route does not fetch operator conversations', async () => {
  window.history.pushState({}, '', '/customer')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const body =
      String(input) === '/api/customer/agents'
        ? { data: [], meta: { total: 0 } }
        : []
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
  })

  render(<App />)
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(fetchMock).not.toHaveBeenCalledWith('/api/chat/conversations', undefined)
})

test('operator route fetches operator conversations for the sidebar', async () => {
  window.history.pushState({}, '', '/operator')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  render(<App />)

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith('/api/chat/conversations', undefined)
  })
})
