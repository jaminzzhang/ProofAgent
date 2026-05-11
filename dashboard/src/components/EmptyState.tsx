interface EmptyStateProps {
  message: string
}

export function EmptyState({ message }: EmptyStateProps) {
  return (
    <div className="flex items-center justify-center py-12 text-[var(--text-muted)] text-sm">
      {message}
    </div>
  )
}
