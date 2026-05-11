interface StatusDotProps {
  status: 'ok' | 'blocked' | 'waiting' | 'error'
  pulse?: boolean
}

const DOT_STYLES = {
  ok: 'bg-green-400',
  blocked: 'bg-red-400',
  waiting: 'bg-blue-400',
  error: 'bg-red-500',
}

export function StatusDot({ status, pulse }: StatusDotProps) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${DOT_STYLES[status]} ${status === 'waiting' || pulse ? 'animate-pulse' : ''}`}
      role="img"
      aria-label={status}
    />
  )
}
