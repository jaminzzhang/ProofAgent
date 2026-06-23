import { OUTCOME_STYLES, outcomeCategory, type ReceiptOutcome } from '@proofagent/ui'
import type {
  TraceEvent,
  WorkflowRunProjection,
} from '../../api/types'

interface WorkflowFlowDiagramProps {
  projection: WorkflowRunProjection
  events?: TraceEvent[]
}

/**
 * Run Flow Diagram — a left-to-right flow of Workflow Stage nodes for one run.
 * Encodes each stage's visited state, terminal outcome, and ReAct self-loop
 * iteration count as visual channels so an operator can read which stages ran,
 * where a Refusal occurred, and how many reasoning cycles elapsed without
 * parsing trace events. See ADR-0044.
 */
export function WorkflowFlowDiagram({ projection, events = [] }: WorkflowFlowDiagramProps) {
  const eventsById = new Map(events.map((event) => [event.event_id, event]))

  return (
    <section
      data-testid="workflow-flow-diagram"
      aria-label="Run flow diagram"
      className="flex items-stretch gap-2 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4"
    >
      {projection.stages.map((stageProjection) => (
        <FlowNode
          key={stageProjection.stage_id}
          stage={stageProjection}
          reactIterationCount={countReactIterations(stageProjection, eventsById)}
        />
      ))}
    </section>
  )
}

/**
 * ReAct Self-Loop Iteration Count: the number of `reasoning_summary` trace
 * events linked to this stage. We count reasoning (not action_proposal) so a
 * retried action that shares an action_id across iterations does not
 * over-count, and so a refusal path that skips reasoning reads as zero loops
 * rather than one. See ADR-0044 and CONTEXT.md.
 */
function countReactIterations(
  stage: WorkflowRunProjection['stages'][number],
  eventsById: Map<string, TraceEvent>,
): number {
  let count = 0
  for (const eventId of stage.related_event_ids) {
    const event = eventsById.get(eventId)
    if (event?.event_type === 'reasoning_summary') count += 1
  }
  return count
}

function FlowNode({
  stage,
  reactIterationCount,
}: {
  stage: WorkflowRunProjection['stages'][number]
  reactIterationCount: number
}) {
  const outcome = stage.outcome as ReceiptOutcome | null
  const outcomeCategoryValue = outcome ? outcomeCategory(outcome) : null
  const outcomeBorderClass = outcomeCategoryValue
    ? CATEGORY_BORDER[outcomeCategoryValue]
    : 'border-[var(--border)]'

  return (
    <article
      data-testid={`flow-node-${stage.stage_id}`}
      data-visited={stage.visited ? 'true' : 'false'}
      data-outcome-category={outcomeCategoryValue ?? 'none'}
      className={`relative flex min-w-[8rem] flex-col rounded-md border px-3 py-2 ${
        stage.visited ? outcomeBorderClass : 'border-dashed border-[var(--border-strong)]'
      } ${stage.visited ? 'bg-[var(--bg-base)]' : 'bg-[var(--bg-subtle)]'}`}
    >
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
        {stage.label ?? stage.stage_id}
      </span>
      {!stage.visited && (
        <span className="mt-1 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
          not visited
        </span>
      )}
      {outcome && (
        <span className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          {OUTCOME_STYLES[outcome].defaultLabel}
        </span>
      )}
      {reactIterationCount > 0 && (
        <span
          aria-label={`ReAct iterations: ${reactIterationCount}`}
          className="absolute -right-2 -top-2 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--accent-fg)]"
        >
          ⟲ ×{reactIterationCount}
        </span>
      )}
    </article>
  )
}

// Border color per outcome category, reusing the canonical OutcomeBadge
// grouping so the diagram shares one color language with the rest of the app.
const CATEGORY_BORDER: Record<string, string> = {
  success: 'border-[var(--success-border)]',
  warning: 'border-[var(--warning-border)]',
  danger: 'border-[var(--danger-border)]',
  neutral: 'border-[var(--neutral-border)]',
}
