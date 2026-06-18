import { cn } from '../lib/cn'

interface StatusDotProps {
  status: 'ok' | 'blocked' | 'waiting' | 'error' | 'connected'
  pulse?: boolean
  className?: string
}

/**
 * Status dot for live/connection indicators. Uses semantic tokens
 * (not raw Tailwind palette colors) so it themes correctly in dark mode.
 */
const DOT_STYLES: Record<StatusDotProps['status'], string> = {
  ok: 'bg-[var(--success)]',
  blocked: 'bg-[var(--danger)]',
  waiting: 'bg-[var(--warning)]',
  error: 'bg-[var(--danger)]',
  connected: 'bg-[var(--success)]',
}

export function StatusDot({ status, pulse, className }: StatusDotProps) {
  const shouldPulse = status === 'waiting' || pulse
  return (
    <span
      className={cn(
        'inline-block w-2 h-2 rounded-full',
        DOT_STYLES[status],
        shouldPulse && 'animate-pulse',
        className,
      )}
      role="img"
      aria-label={status}
    />
  )
}
