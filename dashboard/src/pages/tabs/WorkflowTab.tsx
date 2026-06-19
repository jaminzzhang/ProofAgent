import { CodeBlock, CopyButton } from '@proofagent/ui'
import type {
  TraceEvent,
  WorkflowRunProjection,
  WorkflowRunStageProjection,
} from '../../api/types'
import { formatTraceTime, stringifyTraceValue, traceEventLabel } from './traceDisplay'

interface WorkflowTabProps {
  projection: WorkflowRunProjection
  events?: TraceEvent[]
}

export function WorkflowTab({ projection, events = [] }: WorkflowTabProps) {
  const eventsById = new Map(events.map((event) => [event.event_id, event]))

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <WorkflowFact label="Workflow Template" value={projection.template_name ?? 'Unknown'} />
          <WorkflowFact
            label="Descriptor"
            value={projection.template_descriptor_version ?? 'Unknown'}
          />
          <WorkflowFact
            label="Source"
            value={formatSource(projection.stage_configuration_source)}
          />
        </div>
      </section>

      {projection.stages.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)]">
          No Workflow stage facts were captured for this run.
        </div>
      ) : (
        <div className="space-y-3">
          {projection.stages.map((stage) => (
            <WorkflowStageCard
              key={stage.stage_id}
              stage={stage}
              traceEvents={traceEventsForStage(stage, eventsById)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function WorkflowStageCard({
  stage,
  traceEvents,
}: {
  stage: WorkflowRunStageProjection
  traceEvents: TraceEvent[]
}) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {stage.label ?? stage.stage_id}
          </h3>
          <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">{stage.stage_id}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill>{stage.visited ? 'visited' : 'configured only'}</Pill>
          {stage.status && <Pill>{stage.status}</Pill>}
          {stage.outcome && <Pill>{stage.outcome}</Pill>}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <WorkflowMap title="Stage Summary" values={stage.safe_summary} />
        <WorkflowMap title="Context Application" values={stage.context_application_summary} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <TokenList title="Produced Fact Refs" values={stage.produced_fact_refs} />
        <TokenList title="Related Trace Events" values={stage.related_event_ids} />
      </div>

      <div className="mt-4">
        <StageTraceList events={traceEvents} />
      </div>

      {(stage.approval_pause_summary || stage.clarification_need_summary) && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {stage.approval_pause_summary && (
            <WorkflowMap title="Approval Pause" values={stage.approval_pause_summary} />
          )}
          {stage.clarification_need_summary && (
            <WorkflowMap title="Clarification Need" values={stage.clarification_need_summary} />
          )}
        </div>
      )}
    </section>
  )
}

function StageTraceList({ events }: { events: TraceEvent[] }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Stage Trace
        </h4>
        {events.length > 0 && <Pill>{`${events.length} runtime events`}</Pill>}
      </div>

      {events.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          No runtime trace events were linked to this stage.
        </p>
      ) : (
        <div className="mt-2 divide-y divide-[var(--border)] rounded-md border border-[var(--border)] bg-[var(--bg-base)]">
          {events.map((event) => (
            <StageTraceEvent key={event.event_id} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}

function StageTraceEvent({ event }: { event: TraceEvent }) {
  const detail = traceEventDetail(event)

  return (
    <article className="px-3 py-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[var(--text-primary)]">
              {traceEventLabel(event.event_type)}
            </span>
            <span className="rounded bg-[var(--bg-hover)] px-2 py-0.5 font-mono text-xs text-[var(--text-primary)]">
              #{event.sequence}
            </span>
            <span className="font-mono text-xs text-[var(--text-muted)]">
              {formatTraceTime(event.timestamp)}
            </span>
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-[var(--text-muted)]">
            <span className="break-all font-mono">{event.event_id}</span>
            <CopyButton value={event.event_id} label="Copy event id" size={12} />
          </div>
        </div>
        <Pill>{event.status}</Pill>
      </div>

      {detail && (
        <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
          {detail}
        </p>
      )}

      <details className="mt-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)]">
        <summary className="cursor-pointer px-3 py-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Full JSON event
        </summary>
        <CodeBlock className="max-h-72 rounded-none border-x-0 border-b-0">
          {stringifyTraceValue(event)}
        </CodeBlock>
      </details>
    </article>
  )
}

function WorkflowFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </div>
      <div className="mt-1 truncate font-mono text-xs text-[var(--text-primary)]" title={value}>
        {value}
      </div>
    </div>
  )
}

function WorkflowMap({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h4>
      {entries.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">None</p>
      ) : (
        <dl className="mt-2 space-y-2">
          {entries.map(([key, value]) => (
            <div key={key} className="grid gap-1 text-xs sm:grid-cols-[140px_minmax(0,1fr)]">
              <dt className="font-mono text-[var(--text-muted)]">{key}</dt>
              <dd className="break-words text-[var(--text-primary)]">{formatValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function TokenList({ title, values }: { title: string; values: string[] }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h4>
      {values.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">None</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="rounded bg-[var(--bg-hover)] px-2 py-0.5 font-mono text-xs text-[var(--text-primary)]"
            >
              {value}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Pill({ children }: { children: string }) {
  return (
    <span className="rounded-full bg-[var(--bg-hover)] px-2 py-1 font-mono text-xs text-[var(--text-secondary)]">
      {children}
    </span>
  )
}

function traceEventsForStage(
  stage: WorkflowRunStageProjection,
  eventsById: Map<string, TraceEvent>,
): TraceEvent[] {
  return stage.related_event_ids
    .map((eventId) => eventsById.get(eventId))
    .filter((event): event is TraceEvent => Boolean(event))
    .filter((event) => event.event_type !== 'workflow_stage_configuration_trace_summary')
    .sort((left, right) => left.sequence - right.sequence)
}

function traceEventDetail(event: TraceEvent): string | null {
  const payload = event.payload ?? {}

  if (event.event_type === 'workflow_stage_context_applied') {
    const promptFields = payload.prompt_fields
    if (Array.isArray(promptFields) && promptFields.length > 0) {
      return `Prompt fields: ${promptFields.map(String).join(', ')}`
    }
    return payload.stage_id ? `Stage: ${String(payload.stage_id)}` : null
  }

  if (event.event_type === 'workflow_stage_result') {
    return [
      payload.stage_id,
      payload.status ?? event.status,
      payload.outcome,
    ]
      .filter(hasDisplayValue)
      .map(String)
      .join(' / ')
  }

  if (event.event_type === 'pending_approval_created' || event.event_type === 'approval_requested') {
    return `Tool approval for ${String(payload.tool_name ?? 'unknown tool')}`
  }

  if (event.event_type === 'model_request') {
    return `${String(payload.role ?? 'model')} input, ${String(payload.message_count ?? '?')} messages`
  }

  if (event.event_type === 'model_response') {
    const usage = isRecord(payload.token_usage) ? payload.token_usage : payload.usage
    if (isRecord(usage)) {
      return `Token usage: ${String(usage.input_tokens ?? '?')} in / ${String(usage.output_tokens ?? '?')} out`
    }
    return `${String(payload.content_length ?? '?')} response characters`
  }

  if (event.event_type === 'retrieval_result') {
    const count = payload.candidate_count ?? payload.chunk_count ?? payload.result_count
    return `${String(count ?? '?')} retrieval candidates`
  }

  if (payload.stage_id) return `Stage: ${String(payload.stage_id)}`
  return null
}

function hasDisplayValue(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function formatSource(source: Record<string, unknown>) {
  const sourceType = source.source_type
  const reference = source.reference
  if (typeof sourceType === 'string' && typeof reference === 'string') {
    return `${sourceType} / ${reference}`
  }
  if (typeof sourceType === 'string') return sourceType
  if (typeof reference === 'string') return reference
  return 'Unknown'
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  if (value === null || value === undefined) return 'None'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
