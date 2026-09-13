/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import * as api from '../../api/client'
import type { TaskQuestion, WorkflowTaskResponse } from '../../api/workflowTasks'
import { GoalTaskPanel, TaskQuestionForm } from './GoalTaskPanel'

vi.mock('../../api/client', () => ({
  answerWorkflowTask: vi.fn(), changeWorkflowTaskPhase: vi.fn(), createWorkflowTask: vi.fn(),
  fetchWorkflowTask: vi.fn(), resumeWorkflowTask: vi.fn(), reviseWorkflowTaskGoal: vi.fn(), waitForWorkflowTask: vi.fn(),
}))

function question(): TaskQuestion {
  return { status: 'pending', request: {
    question_id: 'q1', task_id: 'task1', goal_revision: 2, stage: 'goal', blocking: true,
    fields: [{ name: 'confirmed', label: 'Confirm scope', value_type: 'boolean', required: true, choices: [], max_length: 2048 }],
    affected_criteria: ['c1'], expires_at: '2099-01-01T00:00:00Z', dedupe_key: 'scope', checkpoint_ref: 'checkpoint:1',
  } }
}
function response(): WorkflowTaskResponse {
  return { run_id: null, task: {
    schema_version: 1, version: 3, phase: 'waiting_for_input', owner: { actor_subject: 'actor', agent_id: 'agent1', agent_version: 'v1' },
    goal: { task_id: 'task1', revision: 2, objective: 'Verify reimbursement', source_input_ref: 'input:1',
      acceptance_criteria: [{ criterion_id: 'c1', description: 'Policy source', verifier: 'source_support', required: true }], constraints: [], required_context: [] },
    assessments: [], questions: [question()], budget_usage: { model_calls: 1, retrieval_calls: 0, tool_calls: 0, tokens: 42 },
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } }
}
const props = { agentId: 'agent1', allowUntrustedWebSupplement: false, onTaskReference: vi.fn(), onBack: vi.fn() }
const tr = (_zh: string, en: string) => en
beforeEach(() => vi.clearAllMocks())
afterEach(() => { cleanup(); vi.restoreAllMocks() })

test('blank boolean does not imply approval; false remains a typed answer and retry reuses identity', async () => {
  const onAnswer = vi.fn().mockResolvedValue(false)
  render(<TaskQuestionForm question={question()} revision={2} disabled={false} tr={tr} onAnswer={onAnswer} />)
  fireEvent.submit(screen.getByRole('button', { name: 'Submit answer and continue' }).closest('form')!)
  expect(onAnswer).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Confirm scope *'), { target: { value: 'false' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit answer and continue' }))
  await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(1))
  expect(onAnswer.mock.calls[0][0]).toEqual({ confirmed: false })
  expect(screen.getByLabelText('Confirm scope *')).toHaveValue('false')
  fireEvent.click(screen.getByRole('button', { name: 'Submit answer and continue' }))
  await waitFor(() => expect(onAnswer).toHaveBeenCalledTimes(2))
  expect(onAnswer.mock.calls[1][1]).toBe(onAnswer.mock.calls[0][1])
})

test.each(['answered', 'expired', 'superseded', 'old-revision', 'timeout'] as const)('%s question cannot be submitted', async status => {
  const item = question()
  if (status === 'old-revision') item.request.goal_revision = 1
  else if (status === 'timeout') item.request.expires_at = '2000-01-01T00:00:00Z'
  else item.status = status
  const onAnswer = vi.fn()
  render(<TaskQuestionForm question={item} revision={2} disabled={false} tr={tr} onAnswer={onAnswer} />)
  expect(screen.getByRole('button', { name: 'Submit answer and continue' })).toBeDisabled()
  fireEvent.submit(screen.getByRole('button', { name: 'Submit answer and continue' }).closest('form')!)
  expect(onAnswer).not.toHaveBeenCalled()
})

test('creation failure preserves the objective and idempotency identity', async () => {
  vi.mocked(api.createWorkflowTask).mockRejectedValue(new Error('network'))
  render(<GoalTaskPanel {...props} />)
  fireEvent.change(screen.getByLabelText('Task objective'), { target: { value: 'Keep this objective' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create and run' }))
  await screen.findByRole('alert')
  expect(screen.getByLabelText('Task objective')).toHaveValue('Keep this objective')
  fireEvent.click(screen.getByRole('button', { name: 'Create and run' }))
  await waitFor(() => expect(api.createWorkflowTask).toHaveBeenCalledTimes(2))
  const calls = vi.mocked(api.createWorkflowTask).mock.calls
  expect(calls[0][1]).toBe(calls[1][1])
})

test('reload restores the pinned task and answer submits its current goal revision', async () => {
  vi.mocked(api.fetchWorkflowTask).mockResolvedValue(response())
  const answered = response()
  answered.task.questions[0].status = 'answered'
  answered.task.version = 4
  vi.mocked(api.answerWorkflowTask).mockResolvedValue(answered)
  render(<GoalTaskPanel {...props} initialTaskId="task1" initialAgentVersion="v1" />)
  await screen.findByText('Verify reimbursement')
  expect(api.fetchWorkflowTask).toHaveBeenCalledWith('task1', { agent_id: 'agent1', agent_version: 'v1' })
  fireEvent.change(screen.getByLabelText('Confirm scope *'), { target: { value: 'true' } })
  fireEvent.click(screen.getByRole('button', { name: 'Submit answer and continue' }))
  await waitFor(() => expect(api.answerWorkflowTask).toHaveBeenCalledWith('task1', response().task.owner, expect.objectContaining({
    question_id: 'q1', expected_goal_revision: 2, values: { confirmed: true },
  })))
  expect(await screen.findByText('Answered')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Submit answer and continue' })).toBeDisabled()
})

test('failure to reload a known task offers retry instead of creating a replacement', async () => {
  vi.mocked(api.fetchWorkflowTask).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(response())
  render(<GoalTaskPanel {...props} initialTaskId="task1" initialAgentVersion="v1" />)
  await screen.findByRole('alert')
  expect(screen.queryByRole('button', { name: 'Create and run' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Retry task' }))
  expect(await screen.findByText('Verify reimbursement')).toBeInTheDocument()
})

test('paused task with a blocking question resumes to input instead of dispatching unanswered work', async () => {
  const paused = response(); paused.task.phase = 'paused'
  vi.mocked(api.fetchWorkflowTask).mockResolvedValue(paused)
  vi.mocked(api.resumeWorkflowTask).mockResolvedValue(response())
  render(<GoalTaskPanel {...props} initialTaskId="task1" initialAgentVersion="v1" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Resume task' }))
  await waitFor(() => expect(api.resumeWorkflowTask).toHaveBeenCalledWith('task1', paused.task.owner))
  expect(api.changeWorkflowTaskPhase).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.getByLabelText('Confirm scope *')).not.toBeDisabled())
})

test('expired questions offer an explicit renewal through the guarded resume endpoint', async () => {
  const expired = response(); expired.task.questions[0].status = 'expired'
  vi.mocked(api.fetchWorkflowTask).mockResolvedValue(expired)
  vi.mocked(api.resumeWorkflowTask).mockResolvedValue(response())
  render(<GoalTaskPanel {...props} initialTaskId="task1" initialAgentVersion="v1" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Renew questions' }))
  await waitFor(() => expect(api.resumeWorkflowTask).toHaveBeenCalledWith('task1', expired.task.owner))
  await waitFor(() => expect(screen.getByLabelText('Confirm scope *')).not.toBeDisabled())
})

test('committed answers remain visible after reload', async () => {
  const item = question(); item.status = 'answered'; item.answer = { values: { confirmed: false } }
  render(<TaskQuestionForm question={item} revision={2} disabled={false} tr={tr} onAnswer={vi.fn()} />)
  expect(screen.getByLabelText('Confirm scope *')).toHaveValue('false')
})
