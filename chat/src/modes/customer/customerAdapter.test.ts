import { afterEach, expect, test, vi } from 'vitest'

import {
  createCustomerConversation,
  createCustomerRun,
  normalizeCustomerTurn,
} from './customerAdapter'

afterEach(() => {
  vi.restoreAllMocks()
})

test('createCustomerConversation uses customer run API', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ conversation_id: 'cust_conv_1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await createCustomerConversation('insurance_customer_service', 'CUST-001')

  expect(fetchMock).toHaveBeenCalledWith('/api/customer/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: 'insurance_customer_service',
      customer_id: 'CUST-001',
    }),
  })
})

test('createCustomerRun submits customer questions through customer run API', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ message: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await createCustomerRun('cust_conv_1', 'What is my policy status?')

  expect(fetchMock).toHaveBeenCalledWith('/api/customer/conversations/cust_conv_1/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: 'What is my policy status?' }),
  })
})

test('normalizeCustomerTurn keeps only customer-safe display fields', () => {
  const normalized = normalizeCustomerTurn({
    turn_id: 'cust_turn_1',
    run_id: 'run_secret',
    question: 'What is my policy status?',
    created_at: '2026-05-21T00:00:00Z',
    response_snapshot: {
      conversation_id: 'cust_conv_1',
      turn_id: 'cust_turn_1',
      run_id: 'run_secret',
      progress_state: 'completed',
      message: 'Your policy status is active.',
      safe_sources: ['policy_status_lookup'],
      links: { receipt: '/api/runs/run_secret/receipt' },
      governance_details: { review: 'internal' },
      approval_state: { state: 'requested' },
      internal_handoff_status: 'created',
    },
  } as never)

  expect(normalized.id).toBe('cust_turn_1')
  expect(normalized.assistant.content).toBe('Your policy status is active.')
  expect(normalized.assistant.sources).toEqual(['policy_status_lookup'])
  expect(JSON.stringify(normalized)).not.toContain('run_secret')
  expect(JSON.stringify(normalized)).not.toContain('governance_details')
  expect(JSON.stringify(normalized)).not.toContain('approval_state')
  expect(JSON.stringify(normalized)).not.toContain('receipt')
  expect(JSON.stringify(normalized)).not.toContain('internal_handoff')
})
