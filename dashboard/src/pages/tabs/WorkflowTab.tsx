import { CodeBlock, CopyButton } from '@proofagent/ui'
import { useState, type ReactNode } from 'react'
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

// Runtime event types that are folded into the "model" badge (a request/response
// pair is one model call, so both map to the same readable noun).
const MODEL_EVENT_TYPES = new Set(['model_request', 'model_response', 'model_error'])

// Map raw trace event types to short, scannable badge nouns. Types not listed
// here are shown verbatim via traceEventLabel so nothing is silently dropped.
const BADGE_NOUN: Record<string, string> = {
  policy_decision: 'policy',
  review_requested: 'review',
  review_decision: 'review',
  review_error: 'review',
  review_overridden: 'review',
  retrieval_step: 'retrieval',
  retrieval_result: 'retrieval',
  retrieval_plan: 'retrieval',
  retrieval_query_set: 'retrieval',
  retrieval_started: 'retrieval',
  evidence_evaluation: 'evidence',
  intent_resolution: 'intent',
  reasoning_summary: 'reasoning',
  action_proposal: 'action',
  tool_request: 'tool',
  tool_result: 'tool',
  memory_write_decision: 'memory',
  memory_admission: 'memory',
  memory_read: 'memory',
  final_output: 'output',
  final_output_disclosure: 'disclosure',
  approval_requested: 'approval',
  pending_approval_created: 'approval',
  approval_granted: 'approval',
  approval_denied: 'approval',
  workflow_stage_result: 'result',
}

function stageBadgeCounts(events: TraceEvent[]): { noun: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const event of events) {
    const noun = MODEL_EVENT_TYPES.has(event.event_type)
      ? 'model'
      : (BADGE_NOUN[event.event_type] ?? null)
    if (!noun) continue
    counts.set(noun, (counts.get(noun) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([noun, count]) => ({ noun, count }))
    .sort((a, b) => b.count - a.count || a.noun.localeCompare(b.noun))
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
  const [expanded, setExpanded] = useState(false)
  const badges = stageBadgeCounts(traceEvents)
  const stageName = stage.label ?? stage.stage_id
  const hasDetails =
    Object.keys(stage.safe_summary).length > 0 ||
    Object.keys(stage.context_application_summary).length > 0 ||
    stage.produced_fact_refs.length > 0 ||
    stage.related_event_ids.length > 0 ||
    stage.approval_pause_summary !== null ||
    stage.clarification_need_summary !== null

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

      {badges.length > 0 && (
        <p
          data-testid={`stage-badges-${stage.stage_id}`}
          className="mt-3 text-xs text-[var(--text-secondary)]"
        >
          {badges
            .map(({ noun, count }) => (
              <span key={noun} className="mr-1.5 inline-block">
                <span className="font-semibold text-[var(--text-primary)]">{count}</span> {noun}
              </span>
            ))
            .reduce<ReactNode[]>((acc, node, i) => {
              if (i > 0) acc.push(<span key={`sep-${i}`}> · </span>)
              acc.push(node)
              return acc
            }, [])}
        </p>
      )}

      {hasDetails && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? `Collapse ${stageName} stage` : `Expand ${stageName} stage`}
          onClick={() => setExpanded((value) => !value)}
          className="mt-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]"
        >
          <span
            className="inline-block transition-transform"
            style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
            aria-hidden="true"
          >
            ▸
          </span>
          Details
        </button>
      )}

      {expanded && hasDetails && (
        <div className="mt-3 space-y-4">
          {(Object.keys(stage.safe_summary).length > 0 ||
            Object.keys(stage.context_application_summary).length > 0) && (
            <div className="grid gap-4 lg:grid-cols-2">
              <WorkflowMap title="Stage Summary" values={stage.safe_summary} />
              <ContextApplication values={stage.context_application_summary} />
            </div>
          )}

          {(stage.produced_fact_refs.length > 0 || stage.related_event_ids.length > 0) && (
            <div className="grid gap-4 lg:grid-cols-2">
              <TokenList title="Produced Fact Refs" values={stage.produced_fact_refs} />
              <TokenList title="Related Trace Events" values={stage.related_event_ids} />
            </div>
          )}

          <StageTraceList events={traceEvents} />

          {(stage.approval_pause_summary || stage.clarification_need_summary) && (
            <div className="grid gap-4 lg:grid-cols-2">
              {stage.approval_pause_summary && (
                <WorkflowMap title="Approval Pause" values={stage.approval_pause_summary} />
              )}
              {stage.clarification_need_summary && (
                <WorkflowMap title="Clarification Need" values={stage.clarification_need_summary} />
              )}
            </div>
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

// Count-style keys (already self-describing via their name) are collapsed into a
// single human sentence so the key and value no longer duplicate each other.
const CONTEXT_COUNT_KEYS: { key: string; noun: string }[] = [
  { key: 'business_context_length', noun: 'business-context chars' },
  { key: 'task_instruction_count', noun: 'task instructions' },
  { key: 'output_preference_count', noun: 'output preferences' },
]

// Constants that are template-wide, not stage-specific: shown once at the
// Workflow top, never repeated inside every stage card.
const CONTEXT_TEMPLATE_CONSTANT_KEYS = new Set([
  'template_descriptor_version',
  'template_name',
])

// Option-list keys rendered as chips. The `prompt_fields` list is a subset of
// the same context that `context_options` already enumerates, so when both are
// present we keep only the fuller `context_options` to avoid restating tokens.
const CONTEXT_OPTION_KEYS = ['context_options', 'prompt_fields']

function ContextApplication({ values }: { values: Record<string, unknown> }) {
  const counts = CONTEXT_COUNT_KEYS
    .map(({ key, noun }) => ({ noun, value: values[key] }))
    .filter(({ value }) => typeof value === 'number')

  const optionKey = CONTEXT_OPTION_KEYS.find((key) => Array.isArray(values[key]))
  const options = optionKey ? (values[optionKey] as unknown[]).map(String) : []

  const remaining = Object.entries(values).filter(
    ([key, value]) =>
      !CONTEXT_TEMPLATE_CONSTANT_KEYS.has(key) &&
      !CONTEXT_COUNT_KEYS.some((c) => c.key === key) &&
      !(optionKey && key === optionKey) &&
      hasDisplayValue(value),
  )

  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        Context Application
      </h4>
      {counts.length === 0 && options.length === 0 && remaining.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--text-muted)]">None</p>
      ) : (
        <div className="mt-2 space-y-2">
          {counts.length > 0 && (
            <p className="text-xs text-[var(--text-primary)]">
              {counts
                .filter(({ value }) => value !== 0)
                .map(({ value, noun }) => `${value} ${noun}`)
                .join(' · ')}
            </p>
          )}
          {options.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {options.map((option) => (
                <span
                  key={option}
                  className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 text-[var(--text-secondary)] text-xs"
                >
                  {humanizeContextOption(option)}
                </span>
              ))}
            </div>
          )}
          {remaining.length > 0 && (
            <dl className="space-y-1.5">
              {remaining.map(([key, value]) => (
                <div
                  key={key}
                  className="grid gap-1 text-xs sm:grid-cols-[140px_minmax(0,1fr)]"
                >
                  <dt className="font-mono text-[var(--text-muted)]">{key}</dt>
                  <dd className="break-words text-[var(--text-primary)]">
                    {formatValue(value)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
    </div>
  )
}

function humanizeContextOption(option: string): string {
  return option
    .replace(/^include_/, '')
    .replace(/^bound_/, '')
    .replace(/_/g, ' ')
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
