import type { TraceEvent } from '../../api/types'
import { TimelineNode } from './TimelineNode'

interface ErrorNodeProps {
  event: TraceEvent
}

export function ErrorNode({ event }: ErrorNodeProps) {
  const payload = event.payload as Record<string, string>
  const msg = payload.message ?? ''
  return (
    <TimelineNode
      label={event.event_type === 'model_error' ? 'Model error' : 'Run failed'}
      timestamp={event.timestamp}
      status="error"
    >
      <span className="text-red-400">
        {payload.error_code ?? 'UNKNOWN'}
      </span>
      {msg && (
        <span className="ml-1 text-[var(--text-muted)]">{msg}</span>
      )}
    </TimelineNode>
  )
}
