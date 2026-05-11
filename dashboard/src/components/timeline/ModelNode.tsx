import type { TraceEvent } from '../../api/types'
import { TimelineNode } from './TimelineNode'

interface ModelNodeProps {
  event: TraceEvent
}

export function ModelNode({ event }: ModelNodeProps) {
  const payload = event.payload as Record<string, unknown>
  const isRequest = event.event_type === 'model_request'
  const label = isRequest ? 'Model request' : 'Model response'

  return (
    <TimelineNode
      label={label}
      timestamp={event.timestamp}
      status={event.status}
    >
      {isRequest ? (
        <span>
          {String(payload.provider ?? '')} / {String(payload.model ?? '')},{' '}
          {String(payload.message_count ?? '?')} messages
        </span>
      ) : (
        <span>
          {payload.token_usage
            ? `${(payload.token_usage as Record<string, number>).input_tokens ?? '?'} in / ${(payload.token_usage as Record<string, number>).output_tokens ?? '?'} out`
            : `${String(payload.content_length ?? '?')} chars`}
          {payload.finish_reason ? `, finish: ${String(payload.finish_reason as string)}` : ''}
        </span>
      )}
    </TimelineNode>
  )
}
