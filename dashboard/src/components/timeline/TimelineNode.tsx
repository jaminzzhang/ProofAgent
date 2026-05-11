import type { ReactNode } from 'react'
import { StatusDot } from '../StatusDot'

interface TimelineNodeProps {
  label: string
  timestamp: string
  status: 'ok' | 'blocked' | 'waiting' | 'error'
  children?: ReactNode
  onClick?: () => void
}

export function TimelineNode({ label, timestamp, status, children, onClick }: TimelineNodeProps) {
  return (
    <div className="flex gap-3 group">
      <div className="flex flex-col items-center">
        <StatusDot status={status} />
        <div className="w-px flex-1 bg-[var(--border)] group-last:hidden" />
      </div>
      <div className={`pb-4 ${onClick ? 'cursor-pointer' : ''}`} onClick={onClick}>
        <div className="flex items-center gap-2">
          <span className="text-sm text-[var(--text-primary)]">{label}</span>
          <span className="text-xs font-mono text-[var(--text-muted)]">{formatTime(timestamp)}</span>
        </div>
        {children && <div className="mt-1 text-xs text-[var(--text-secondary)]">{children}</div>}
      </div>
    </div>
  )
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}
