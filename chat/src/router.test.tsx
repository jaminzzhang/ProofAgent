// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import { AppRoutes } from './router'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

test('root route links to operator chat only', () => {
  renderRoute('/')

  expect(screen.getByRole('heading', { name: 'Proof Agent Chat' })).toBeTruthy()
  expect(screen.getByRole('link', { name: /operator chat/i })).toHaveAttribute('href', '/operator')
  expect(screen.queryByRole('link', { name: /customer chat/i })).toBeNull()
})

test('legacy un-namespaced chat routes do not open operator chat directly', () => {
  renderRoute('/new')

  expect(screen.getByRole('heading', { name: 'Proof Agent Chat' })).toBeTruthy()
  expect(screen.queryByText('Assisted Chat')).toBeNull()
})

test('operator direct Agent route opens operator chat mode', async () => {
  mockAgentDirectoryFetch('/api/chat/agents', 'enterprise_qa')
  renderRoute('/operator/agents/enterprise_qa/new')

  expect(await screen.findByRole('heading', { name: 'Operator Chat' })).toBeTruthy()
})

function mockAgentDirectoryFetch(url: string, agentId: string) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (request) => {
    if (request === url) {
      return new Response(
        JSON.stringify({
          data: [
            {
              agent_id: agentId,
              display_name: agentId,
              purpose: 'Published test Agent.',
              agent_version_id: 'version_123',
              customer_facing: false,
            },
          ],
          meta: { total: 1 },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )
    }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}
