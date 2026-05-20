export function SourceList({ sources }: { sources: string[] }) {
  if (sources.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap gap-2">
      {sources.map((source) => (
        <span
          key={source}
          className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]"
        >
          {source}
        </span>
      ))}
    </div>
  )
}
