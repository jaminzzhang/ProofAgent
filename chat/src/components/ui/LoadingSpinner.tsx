interface LoadingSpinnerProps {
  size?: 'sm' | 'md'
}

export function LoadingSpinner({ size = 'md' }: LoadingSpinnerProps) {
  const sizeClass = size === 'sm' ? 'w-4 h-4' : 'w-8 h-8'
  return (
    <div className="flex items-center justify-center py-8">
      <div
        className={`${sizeClass} border-2 border-[var(--border)] border-t-[var(--accent)] rounded-full animate-spin`}
        role="status"
        aria-label="Loading"
      />
    </div>
  )
}
