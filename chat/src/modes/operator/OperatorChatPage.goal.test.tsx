/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { OperatorChatPage } from './OperatorChatPage'
import * as adapter from './operatorAdapter'
import * as api from '../../api/client'

vi.mock('./operatorAdapter', () => ({ createOperatorConversation: vi.fn(), createOperatorConversationRun: vi.fn(), fetchOperatorAgents: vi.fn(), fetchOperatorConversation: vi.fn() }))
vi.mock('../../api/client', () => ({ createWorkflowTask: vi.fn(), fetchWorkflowTask: vi.fn(), waitForWorkflowTask: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(adapter.fetchOperatorAgents).mockResolvedValue({ data: [{ agent_id: 'agent1', agent_version_id: 'v2', display_name: 'Example', purpose: '', customer_facing: false }], meta: { total: 1 } })
})
afterEach(cleanup)
function page(url = '/operator/agents/agent1/new') {
  return render(<MemoryRouter initialEntries={[url]}><Routes><Route path="/operator/agents/:agentId/new" element={<OperatorChatPage />} /></Routes></MemoryRouter>)
}

test('ordinary chat is the default and goal tasks require explicit selection', async () => {
  page()
  expect(await screen.findByPlaceholderText('Type your question for the assistant')).toBeInTheDocument()
  expect(api.createWorkflowTask).not.toHaveBeenCalled()
  expect(screen.queryByLabelText('Task objective')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Goal task' }))
  expect(await screen.findByLabelText('Task objective')).toBeInTheDocument()
  expect(adapter.createOperatorConversation).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Regular chat' }))
  expect(await screen.findByPlaceholderText('Type your question for the assistant')).toBeInTheDocument()
})

test('a saved task URL reloads the pinned version independently of the latest Agent release', async () => {
  vi.mocked(api.fetchWorkflowTask).mockRejectedValue(new Error('offline'))
  page('/operator/agents/agent1/new?task=task_123&version=v1')
  await waitFor(() => expect(api.fetchWorkflowTask).toHaveBeenCalledWith('task_123', { agent_id: 'agent1', agent_version: 'v1' }))
  expect(await screen.findByRole('button', { name: 'Retry task' })).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Type your question for the assistant')).not.toBeInTheDocument()
})
