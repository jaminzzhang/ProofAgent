import type { TraceEvent } from '../../api/types'
import { TimelineNode } from '../../components/timeline/TimelineNode'
import { PolicyNode } from '../../components/timeline/PolicyNode'
import { ModelNode } from '../../components/timeline/ModelNode'
import { ErrorNode } from '../../components/timeline/ErrorNode'
import { EmptyState } from '../../components/EmptyState'

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  manifest_loaded: 'Manifest loaded',
  retrieval_started: 'Retrieval started',
  retrieval_result: 'Retrieval result',
  evidence_evaluation: 'Evidence evaluation',
  approval_requested: 'Approval requested',
  approval_granted: 'Approval granted',
  approval_denied: 'Approval denied',
  approval_timeout: 'Approval timeout',
  tool_request: 'Tool request',
  tool_result: 'Tool result',
  memory_read: 'Memory read',
  memory_write_requested: 'Memory write requested',
  memory_write_decision: 'Memory write decision',
  final_output: 'Final output',
  redaction_applied: 'Redaction applied',
  artifact_written: 'Artifact written',
  run_failed: 'Run failed',
}

interface TimelineTabProps {
  events: TraceEvent[]
}

export function TimelineTab({ events }: TimelineTabProps) {
  if (events.length === 0) return <EmptyState message="No trace events." />

  return (
    <div className="py-2">
      {events.map((event) => (
        <EventRenderer key={event.event_id} event={event} />
      ))}
    </div>
  )
}

function EventRenderer({ event }: { event: TraceEvent }) {
  const payload = event.payload as Record<string, unknown>

  if (event.event_type === 'policy_decision') return <PolicyNode event={event} />
  if (event.event_type === 'model_request' || event.event_type === 'model_response') return <ModelNode event={event} />
  if (event.event_type === 'model_error' || event.event_type === 'run_failed') return <ErrorNode event={event} />

  const label = EVENT_LABELS[event.event_type] ?? event.event_type

  let detail: string | null = null
  if (event.event_type === 'retrieval_result') {
    detail = `${payload.chunk_count ?? '?'} chunks retrieved`
  } else if (event.event_type === 'evidence_evaluation') {
    detail = payload.status === 'passed' ? 'passed' : 'blocked'
  } else if (event.event_type === 'final_output') {
    detail = String(payload.outcome ?? '')
  } else if (event.event_type === 'approval_requested') {
    detail = `tool: ${String(payload.tool_name ?? '?')}`
  } else if (event.event_type === 'artifact_written') {
    detail = 'trace.jsonl, governance_receipt.md'
  }

  return (
    <TimelineNode label={label} timestamp={event.timestamp} status={event.status}>
      {detail}
    </TimelineNode>
  )
}
