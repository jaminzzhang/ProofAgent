import { cn } from '../lib/cn'

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  label?: string
  className?: string
}

const SIZE_STYLES = {
  sm: 'w-4 h-4 border-2',
  md: 'w-6 h-6 border-2',
  lg: 'w-8 h-6 border-[3px]',
}

export function LoadingSpinner({
  size = 'md',
  label = 'Loading',
  className,
}: LoadingSpinnerProps) {
  return (
    <div className={cn('flex items-center justify-center py-8', className)}>
      <div
        className={cn(
          'animate-spin rounded-full border-[var(--border)] border-t-[var(--accent)]',
          SIZE_STYLES[size],
        )}
        role="status"
        aria-label={label}
      />
    </div>
  )
}
