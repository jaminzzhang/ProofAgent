import { afterEach, expect, test, vi } from 'vitest'
import {
  fetchConfigAgents,
  fetchRuns,
  importConfigAgent,
  publishConfigDraft,
  rollbackConfigVersion,
  updateConfigDraftContract,
  validateConfigDraft,
  fetchHandoffs,
} from './client'

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

test('fetchRuns includes run purpose filter', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [], meta: { total: 0, limit: 50, offset: 0 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await fetchRuns({ run_purpose: 'validation', search: 'draft' })

  const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost')
  expect(url.pathname).toBe('/api/runs')
  expect(url.searchParams.get('run_purpose')).toBe('validation')
  expect(url.searchParams.get('search')).toBe('draft')
})

test('fetchConfigAgents requests Agent Configuration list', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [], meta: { total: 0 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await fetchConfigAgents()

  expect(fetchMock).toHaveBeenCalledWith('/api/config/agents', undefined)
})

test('importConfigAgent posts manifest path', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_id: 'enterprise_qa', draft_id: 'draft_1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await importConfigAgent({
    manifest_path: 'examples/insurance_customer_service/agent.yaml',
    actor: 'editor',
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/config/agents/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      manifest_path: 'examples/insurance_customer_service/agent.yaml',
      actor: 'editor',
    }),
  })
})

test('validate publish and rollback use configuration lifecycle endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ run_id: 'run_1', run_purpose: 'validation' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ version_id: 'version_1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ version_id: 'version_1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await validateConfigDraft('enterprise_qa', 'draft_1', {
    question: 'What is the reimbursement rule for travel meals?',
    actor: 'validator',
  })
  await publishConfigDraft('enterprise_qa', 'draft_1', {
    validation_run_id: 'run_1',
    actor: 'publisher',
  })
  await rollbackConfigVersion('enterprise_qa', 'version_1', { actor: 'publisher' })

  expect(fetchMock.mock.calls[0][0]).toBe(
    '/api/config/agents/enterprise_qa/drafts/draft_1/validate',
  )
  expect(fetchMock.mock.calls[1][0]).toBe(
    '/api/config/agents/enterprise_qa/drafts/draft_1/publish',
  )
  expect(fetchMock.mock.calls[2][0]).toBe(
    '/api/config/agents/enterprise_qa/versions/version_1/rollback',
  )
})

test('updateConfigDraftContract patches Contract View files', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_yaml: 'name: enterprise_qa' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await updateConfigDraftContract('enterprise_qa', 'draft_1', {
    agent_yaml: 'name: enterprise_qa',
    actor: 'workflow-editor',
  })

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/config/agents/enterprise_qa/drafts/draft_1/contract',
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_yaml: 'name: enterprise_qa',
        actor: 'workflow-editor',
      }),
    },
  )
})
