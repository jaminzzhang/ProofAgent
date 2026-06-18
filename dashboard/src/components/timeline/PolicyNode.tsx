import type { TraceEvent } from '../../api/types'
import { TimelineNode } from './TimelineNode'

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  manifest_loaded: 'Manifest loaded',
  policy_decision: 'Policy decision',
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
  model_request: 'Model request',
  model_response: 'Model response',
  model_error: 'Model error',
  final_output: 'Final output',
  redaction_applied: 'Redaction applied',
  artifact_written: 'Artifact written',
  run_failed: 'Run failed',
}

interface PolicyNodeProps {
  event: TraceEvent
}

export function PolicyNode({ event }: PolicyNodeProps) {
  const payload = event.payload as Record<string, string>
  return (
    <TimelineNode
      label={EVENT_LABELS[event.event_type] ?? event.event_type}
      timestamp={event.timestamp}
      status={event.status}
    >
      <span className={event.status === 'blocked' ? 'text-[var(--danger-fg)]' : 'text-[var(--success-fg)]'}>
        {payload.decision ?? '—'}
      </span>
      {payload.reason && <span className="ml-1 text-[var(--text-muted)]">: {payload.reason}</span>}
    </TimelineNode>
  )
}
