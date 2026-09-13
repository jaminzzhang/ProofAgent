import { afterEach, expect, test, vi } from 'vitest'
import * as api from './client'

afterEach(() => vi.unstubAllGlobals())
const ok = (body: unknown) => ({ ok: true, json: async () => body })
const snapshot = { goal: { task_id: 'task_1' }, owner: { agent_id: 'agent_1', agent_version: 'version:1' }, phase: 'active' }

test('task creation preserves the supplied retry identity and session CSRF', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok({ csrf_token: 'synthetic-csrf' }))
    .mockResolvedValueOnce(ok({ task: snapshot, run_id: 'run_1' }))
  vi.stubGlobal('fetch', fetch)
  await api.initializeOperatorSession()
  await api.createWorkflowTask({ agent_id: 'agent_1', objective: '目标' }, 'stable-create-key')
  expect(fetch.mock.calls[1][0]).toBe('/api/tasks')
  expect(new Headers(fetch.mock.calls[1][1].headers).get('Idempotency-Key')).toBe('stable-create-key')
  expect(new Headers(fetch.mock.calls[1][1].headers).get('X-CSRF-Token')).toBe('synthetic-csrf')
})

test('typed answers retain false and the exact goal revision', async () => {
  const fetch = vi.fn().mockResolvedValue(ok({ task: snapshot, run_id: null }))
  vi.stubGlobal('fetch', fetch)
  await api.answerWorkflowTask('task_1', { agent_id: 'agent_1', agent_version: 'version:1' }, {
    question_id: 'q1', expected_goal_revision: 3, values: { approved: false, count: 0 }, idempotency_key: 'answer-key',
  })
  expect(JSON.parse(fetch.mock.calls[0][1].body).answer).toMatchObject({
    expected_goal_revision: 3, values: { approved: false, count: 0 }, idempotency_key: 'answer-key',
  })
})

test('owner subject is never copied into task URLs or request bodies', async () => {
  const fetch = vi.fn().mockResolvedValue(ok({ task: snapshot, run_id: null }))
  vi.stubGlobal('fetch', fetch)
  const owner = { agent_id: 'agent_1', agent_version: 'version:1', actor_subject: 'private-actor' }
  await api.fetchWorkflowTask('task_1', owner)
  await api.resumeWorkflowTask('task_1', owner)
  expect(JSON.stringify(fetch.mock.calls)).not.toContain('private-actor')
})

test('queued tasks reuse the durable Run result and then refresh task state', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok({ csrf_token: 'test', chat_execution_mode: 'queued' }))
    .mockResolvedValueOnce(ok({ run_id: 'run_1', state: 'succeeded', final_output: { message: 'Verified result' }, failure_code: null }))
    .mockResolvedValueOnce(ok({ task: { ...snapshot, phase: 'complete' }, run_id: 'run_1' }))
  vi.stubGlobal('fetch', fetch)
  await api.initializeOperatorSession()
  const result = await api.waitForWorkflowTask({ task: snapshot, run_id: 'run_1' } as never)
  expect(fetch.mock.calls[1][0]).toBe('/api/runs/run_1')
  expect(fetch.mock.calls[2][0]).toContain('/api/tasks/task_1?')
  expect(result).toMatchObject({ task: { phase: 'complete' }, final_output: 'Verified result', run_state: 'succeeded' })
})

test('a concurrent new Run cannot inherit the previous Run answer', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok({ csrf_token: 'test', chat_execution_mode: 'queued' }))
    .mockResolvedValueOnce(ok({ run_id: 'run_1', state: 'succeeded', final_output: { message: 'Old result' } }))
    .mockResolvedValueOnce(ok({ task: snapshot, run_id: 'run_2' }))
  vi.stubGlobal('fetch', fetch)
  await api.initializeOperatorSession()
  const result = await api.waitForWorkflowTask({ task: snapshot, run_id: 'run_1' } as never)
  expect(result.run_id).toBe('run_2')
  expect(result.final_output).toBeUndefined()
  expect(result.run_state).toBeUndefined()
})
