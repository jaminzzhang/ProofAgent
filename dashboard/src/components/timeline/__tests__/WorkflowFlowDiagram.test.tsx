// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type {
  TraceEvent,
  WorkflowRunProjection,
} from '../../../api/types'
import { WorkflowFlowDiagram } from '../WorkflowFlowDiagram'

afterEach(() => {
  cleanup()
})

function stage(overrides: Partial<WorkflowRunProjection['stages'][number]>): WorkflowRunProjection['stages'][number] {
  return {
    stage_id: 'plan',
    visited: true,
    label: 'Plan',
    status: 'completed',
    outcome: null,
    safe_summary: {},
    context_application_summary: {},
    produced_fact_refs: [],
    related_event_ids: [],
    approval_pause_summary: null,
    clarification_need_summary: null,
    ...overrides,
  }
}

function projection(stages: WorkflowRunProjection['stages'][number][]): WorkflowRunProjection {
  return {
    template_name: 'react_enterprise_qa',
    template_descriptor_version: 'react_enterprise_qa.v1',
    stage_configuration_source: {},
    stages,
  }
}

function event(overrides: Partial<TraceEvent> = {}): TraceEvent {
  return {
    schema_version: 'trace.v1',
    run_id: 'run-1',
    event_id: 'evt_0001',
    sequence: 1,
    timestamp: '2026-06-07T00:00:00Z',
    event_type: 'reasoning_summary',
    span_id: 'span_1',
    status: 'ok',
    payload: {},
    redaction: { applied: false, fields: [] },
    ...overrides,
  }
}

describe('WorkflowFlowDiagram', () => {
  it('renders a stage node with its label', () => {
    render(<WorkflowFlowDiagram projection={projection([stage({ label: 'Plan' })])} events={[]} />)

    expect(screen.getByText('Plan')).toBeInTheDocument()
  })

  it('renders stages in projection order', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({ stage_id: 'intent', label: 'Intent' }),
          stage({ stage_id: 'reasoning', label: 'Reasoning' }),
          stage({ stage_id: 'answer', label: 'Answer' }),
        ])}
        events={[]}
      />,
    )

    const labels = screen.getAllByText(/Intent|Reasoning|Answer/).map((el) => el.textContent)
    expect(labels).toEqual(['Intent', 'Reasoning', 'Answer'])
  })

  it('marks configured-only stages as not visited', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({ stage_id: 'plan', label: 'Plan', visited: true }),
          stage({ stage_id: 'answer', label: 'Answer', visited: false }),
        ])}
        events={[]}
      />,
    )

    expect(screen.getByTestId('flow-node-plan')).toHaveAttribute('data-visited', 'true')
    expect(screen.getByTestId('flow-node-answer')).toHaveAttribute('data-visited', 'false')
    expect(screen.getByTestId('flow-node-answer')).toHaveTextContent('not visited')
  })

  it('shows ReAct iteration count from reasoning_summary events', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({
            stage_id: 'reasoning',
            label: 'Reasoning',
            related_event_ids: ['evt_r1', 'evt_r2', 'evt_r3', 'evt_other'],
          }),
        ])}
        events={[
          event({ event_id: 'evt_r1', sequence: 1, event_type: 'reasoning_summary' }),
          event({ event_id: 'evt_r2', sequence: 2, event_type: 'reasoning_summary' }),
          event({ event_id: 'evt_r3', sequence: 3, event_type: 'reasoning_summary' }),
          event({ event_id: 'evt_other', sequence: 4, event_type: 'action_proposal' }),
        ]}
      />,
    )

    expect(screen.getByTestId('flow-node-reasoning')).toHaveTextContent('×3')
  })

  it('renders no loop badge when reasoning count is zero (refusal path)', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({
            stage_id: 'plan',
            label: 'Plan',
            related_event_ids: ['evt_action_only'],
          }),
        ])}
        events={[
          event({ event_id: 'evt_action_only', sequence: 1, event_type: 'action_proposal' }),
        ]}
      />,
    )

    expect(screen.getByTestId('flow-node-plan')).not.toHaveTextContent('×')
    expect(screen.queryByLabelText(/ReAct iterations/)).not.toBeInTheDocument()
  })

  it('shows the terminal outcome on the stage node', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({
            stage_id: 'answer',
            label: 'Answer',
            outcome: 'ANSWERED_WITH_CITATIONS',
          }),
        ])}
        events={[]}
      />,
    )

    expect(screen.getByTestId('flow-node-answer')).toHaveTextContent('Answered')
    expect(screen.getByTestId('flow-node-answer')).toHaveAttribute('data-outcome-category', 'success')
  })

  it('marks a refused stage node with the neutral outcome category', () => {
    render(
      <WorkflowFlowDiagram
        projection={projection([
          stage({
            stage_id: 'answer',
            label: 'Answer',
            outcome: 'REFUSED_NO_EVIDENCE',
          }),
        ])}
        events={[]}
      />,
    )

    // Refusal is a deliberate policy-correct stop, rendered neutral (not red)
    // per the codebase's canonical OutcomeBadge grouping. See ADR-0044.
    expect(screen.getByTestId('flow-node-answer')).toHaveTextContent('Refused')
    expect(screen.getByTestId('flow-node-answer')).toHaveAttribute('data-outcome-category', 'neutral')
  })
})
