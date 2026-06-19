import {
  Badge,
  CodeBlock,
  CopyButton,
  EmptyState,
  StatusDot,
  type BadgeProps,
} from '@proofagent/ui'
import type {
  TraceEvent,
  WorkflowRunProjection,
  WorkflowRunStageProjection,
} from '../../api/types'

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  manifest_loaded: 'Manifest loaded',
  workflow_stage_configuration_trace_summary: 'Workflow stage configuration',
  workflow_stage_context_applied: 'Stage context applied',
  workflow_stage_result: 'Stage result',
  workflow_stage_completed: 'Stage completed',
  workflow_stage_blocked: 'Stage blocked',
  workflow_stage_waiting: 'Stage waiting',
  intent_resolution: 'Intent resolution',
  retrieval_query_set: 'Retrieval query set',
  business_flow_skill_pack_admission: 'Business flow admission',
  reasoning_summary: 'Reasoning summary',
  action_proposal: 'Action proposal',
  review_requested: 'Review requested',
  review_decision: 'Review decision',
  review_error: 'Review error',
  review_overridden: 'Review overridden',
  clarification_requested: 'Clarification requested',
  policy_decision: 'Policy decision',
  retrieval_started: 'Retrieval started',
  retrieval_plan: 'Retrieval plan',
  retrieval_step: 'Retrieval step',
  retrieval_result: 'Retrieval result',
  evidence_evaluation: 'Evidence evaluation',
  context_admission: 'Context admission',
  approval_requested: 'Approval requested',
  pending_approval_created: 'Pending approval created',
  approval_granted: 'Approval granted',
  approval_denied: 'Approval denied',
  approval_timeout: 'Approval timeout',
  customer_handoff_created: 'Customer handoff created',
  tool_request: 'Tool request',
  tool_result: 'Tool result',
  memory_read: 'Memory read',
  memory_candidate_generated: 'Memory candidate generated',
  memory_write_requested: 'Memory write requested',
  memory_write_decision: 'Memory write decision',
  memory_admission: 'Memory admission',
  memory_export_decision: 'Memory export decision',
  memory_delete_decision: 'Memory delete decision',
  model_request: 'Model request',
  model_connection_resolution: 'Model connection resolution',
  model_response: 'Model response',
  model_error: 'Model error',
  model_output_normalization_failed: 'Model output normalization failed',
  final_output: 'Final output',
  final_output_disclosure: 'Final output disclosure',
  redaction_applied: 'Redaction applied',
  artifact_written: 'Artifact written',
  run_failed: 'Run failed',
}

interface TimelineTabProps {
  events: TraceEvent[]
  projection?: WorkflowRunProjection
}

interface TraceGroup {
  key: string
  title: string
  subtitle?: string
  events: TraceEvent[]
  badges?: TraceBadge[]
  emptyMessage?: string
}

interface TraceBadge {
  label: string
  variant?: BadgeProps['variant']
}

interface TraceSection {
  title: string
  value: unknown
}

export function TimelineTab({ events, projection }: TimelineTabProps) {
  if (events.length === 0) return <EmptyState message="No trace events." />

  const groups = buildTraceGroups(events, projection)

  return (
    <div className="space-y-4 py-2">
      {groups.map((group) => (
        <TraceGroupSection key={group.key} group={group} />
      ))}
    </div>
  )
}

function TraceGroupSection({ group }: { group: TraceGroup }) {
  return (
    <section className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">
            {group.title}
          </h3>
          {group.subtitle && (
            <p className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">
              {group.subtitle}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {(group.badges ?? []).map((badge) => (
            <Badge key={badge.label} variant={badge.variant ?? 'subtle'}>
              {badge.label}
            </Badge>
          ))}
          <Badge variant="outline">{group.events.length} events</Badge>
        </div>
      </div>

      {group.events.length === 0 ? (
        <div className="px-4 py-5 text-sm text-[var(--text-muted)]">
          {group.emptyMessage ?? 'No trace events are linked to this stage.'}
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {group.events.map((event) => (
            <TraceEventRow key={event.event_id} event={event} />
          ))}
        </div>
      )}
    </section>
  )
}

function TraceEventRow({ event }: { event: TraceEvent }) {
  const label = EVENT_LABELS[event.event_type] ?? event.event_type
  const detail = eventDetail(event)
  const callSections = callSectionsForEvent(event)
  const redactionApplied = isRecord(event.redaction) && event.redaction.applied === true

  return (
    <article className="px-4 py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusDot status={event.status} />
            <span className="text-sm font-medium text-[var(--text-primary)]">
              {label}
            </span>
            <Badge variant="outline" className="font-mono">
              #{event.sequence}
            </Badge>
            <span className="font-mono text-xs text-[var(--text-muted)]">
              {formatTime(event.timestamp)}
            </span>
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-[var(--text-muted)]">
            <span className="font-mono">{event.event_id}</span>
            <CopyButton value={event.event_id} label="Copy event id" size={12} />
            {event.span_id && (
              <span className="break-all font-mono">span: {event.span_id}</span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={statusVariant(event.status)}>{event.status}</Badge>
          {redactionApplied && <Badge variant="warning">redacted</Badge>}
        </div>
      </div>

      {detail && (
        <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          {detail}
        </p>
      )}

      {callSections.length > 0 && (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {callSections.map((section) => (
            <TraceValueBlock
              key={`${event.event_id}-${section.title}`}
              title={section.title}
              value={section.value}
            />
          ))}
        </div>
      )}

      <details className="mt-3 rounded-md border border-[var(--border)] bg-[var(--bg-base)]">
        <summary className="cursor-pointer px-3 py-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          Full JSON event
        </summary>
        <CodeBlock className="max-h-96 rounded-none border-x-0 border-b-0">
          {stringifyTraceValue(event)}
        </CodeBlock>
      </details>
    </article>
  )
}

function TraceValueBlock({ title, value }: TraceSection) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </div>
      <CodeBlock className="max-h-64">{stringifyTraceValue(value)}</CodeBlock>
    </div>
  )
}

function buildTraceGroups(
  events: TraceEvent[],
  projection?: WorkflowRunProjection,
): TraceGroup[] {
  const sortedEvents = [...events].sort((left, right) => left.sequence - right.sequence)
  if (!projection || projection.stages.length === 0) {
    return [
      {
        key: 'all',
        title: 'Trace events',
        subtitle: 'JSONL sequence order',
        events: sortedEvents,
      },
    ]
  }

  const eventsById = new Map(sortedEvents.map((event) => [event.event_id, event]))
  const stageRefsByEventId = new Map<string, Set<string>>()

  for (const stage of projection.stages) {
    for (const eventId of stage.related_event_ids) {
      if (!eventsById.has(eventId)) continue
      const refs = stageRefsByEventId.get(eventId) ?? new Set<string>()
      refs.add(stage.stage_id)
      stageRefsByEventId.set(eventId, refs)
    }
  }

  const sharedEventIds = new Set(
    [...stageRefsByEventId.entries()]
      .filter(([, stageIds]) => stageIds.size > 1)
      .map(([eventId]) => eventId),
  )
  const groupedEventIds = new Set<string>()
  const groups: TraceGroup[] = []
  const sharedEvents = sortedEvents.filter((event) => sharedEventIds.has(event.event_id))

  for (const event of sharedEvents) groupedEventIds.add(event.event_id)
  if (sharedEvents.length > 0) {
    groups.push({
      key: 'run-level-shared',
      title: 'Run-level / shared trace',
      subtitle: 'Events linked to more than one workflow stage',
      events: sharedEvents,
    })
  }

  for (const stage of projection.stages) {
    const stageEvents = stage.related_event_ids
      .filter((eventId) => !sharedEventIds.has(eventId))
      .map((eventId) => eventsById.get(eventId))
      .filter((event): event is TraceEvent => Boolean(event))
      .sort((left, right) => left.sequence - right.sequence)

    for (const event of stageEvents) groupedEventIds.add(event.event_id)
    groups.push(traceGroupForStage(stage, stageEvents))
  }

  const unassignedEvents = sortedEvents.filter((event) => !groupedEventIds.has(event.event_id))
  if (unassignedEvents.length > 0) {
    groups.push({
      key: 'unassigned',
      title: 'Unassigned trace events',
      subtitle: 'Events not linked by the workflow projection',
      events: unassignedEvents,
    })
  }

  return groups
}

function traceGroupForStage(
  stage: WorkflowRunStageProjection,
  events: TraceEvent[],
): TraceGroup {
  const badges: TraceBadge[] = []
  if (stage.status) badges.push({ label: stage.status, variant: statusVariant(stage.status) })
  if (stage.outcome) badges.push({ label: stage.outcome, variant: 'outline' })

  return {
    key: `stage-${stage.stage_id}`,
    title: stage.label ?? stage.stage_id,
    subtitle: stage.stage_id,
    events,
    badges,
  }
}

function callSectionsForEvent(event: TraceEvent): TraceSection[] {
  const payload = event.payload ?? {}
  const sections: TraceSection[] = []

  if (event.event_type === 'action_proposal') {
    pushSection(sections, 'Action', pickPayload(payload, [
      'action_id',
      'action_type',
      'target_tool_name',
      'risk_level',
    ]))
    pushSection(sections, 'Parameters', payload.parameters)
    return sections
  }

  if (event.event_type === 'pending_approval_created') {
    pushSection(sections, 'Parameters', payload.parameters)
    pushSection(sections, 'Approval Context', pickPayload(payload, [
      'approval_id',
      'action_id',
      'tool_name',
      'policy_decision',
      'checkpoint_id',
      'expires_at',
    ]))
    return sections
  }

  if (
    [
      'model_request',
      'review_requested',
      'retrieval_step',
      'tool_request',
      'memory_read',
      'memory_write_requested',
      'approval_requested',
    ].includes(event.event_type)
  ) {
    pushSection(sections, 'Input', payload)
    return sections
  }

  if (
    [
      'model_response',
      'model_error',
      'model_output_normalization_failed',
      'review_decision',
      'review_error',
      'review_overridden',
      'retrieval_result',
      'tool_result',
      'memory_write_decision',
      'memory_admission',
      'memory_export_decision',
      'memory_delete_decision',
      'policy_decision',
      'evidence_evaluation',
    ].includes(event.event_type)
  ) {
    pushSection(sections, outputSectionTitle(event.event_type), payload)
    return sections
  }

  if (event.event_type === 'retrieval_plan' || event.event_type === 'retrieval_query_set') {
    pushSection(sections, 'Plan', payload)
    return sections
  }

  return sections
}

function pushSection(sections: TraceSection[], title: string, value: unknown) {
  if (hasDisplayValue(value)) sections.push({ title, value })
}

function pickPayload(payload: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(
    keys
      .filter((key) => hasDisplayValue(payload[key]))
      .map((key) => [key, payload[key]]),
  )
}

function outputSectionTitle(eventType: string): string {
  if (
    eventType === 'model_error' ||
    eventType === 'review_error' ||
    eventType === 'model_output_normalization_failed'
  ) {
    return 'Error'
  }
  if (eventType.endsWith('_decision') || eventType === 'policy_decision') return 'Decision'
  return 'Output'
}

function eventDetail(event: TraceEvent): string | null {
  const payload = event.payload ?? {}

  if (event.event_type === 'retrieval_result') {
    const count = payload.candidate_count ?? payload.chunk_count ?? payload.result_count
    return `${String(count ?? '?')} retrieval candidates`
  }
  if (event.event_type === 'evidence_evaluation') {
    const status = payload.status ?? event.status
    return `Evidence validation ${String(status)}`
  }
  if (event.event_type === 'final_output') {
    return String(payload.outcome ?? '')
  }
  if (event.event_type === 'approval_requested' || event.event_type === 'pending_approval_created') {
    return `Tool approval for ${String(payload.tool_name ?? 'unknown tool')}`
  }
  if (event.event_type === 'tool_request' || event.event_type === 'tool_result') {
    return `Tool: ${String(payload.tool_name ?? 'unknown')}`
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
  if (event.event_type === 'policy_decision') {
    return `${String(payload.decision ?? 'unknown decision')}${payload.reason ? `: ${String(payload.reason)}` : ''}`
  }
  if (event.event_type === 'artifact_written') {
    return 'Trace and receipt artifacts recorded'
  }
  if (event.event_type === 'workflow_stage_result') {
    return `${String(payload.stage_id ?? 'stage')} ${String(payload.status ?? event.status)}`
  }
  if (event.event_type === 'run_failed' || event.event_type === 'model_error') {
    return `${String(payload.error_code ?? 'UNKNOWN')}${payload.message ? `: ${String(payload.message)}` : ''}`
  }

  return null
}

function statusVariant(status: string): BadgeProps['variant'] {
  if (status === 'ok' || status === 'completed') return 'success'
  if (status === 'waiting') return 'warning'
  if (status === 'blocked' || status === 'error') return 'danger'
  if (status === 'skipped') return 'neutral'
  return 'subtle'
}

function stringifyTraceValue(value: unknown): string {
  if (value === undefined) return 'undefined'
  try {
    const json = JSON.stringify(value, null, 2)
    return json === undefined ? String(value) : json
  } catch {
    return String(value)
  }
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

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ts
  }
}
