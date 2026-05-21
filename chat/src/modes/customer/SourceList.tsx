import type { CustomerSafeSource } from '../../api/types'

export function SourceList({ sources }: { sources: Array<string | CustomerSafeSource> }) {
  if (sources.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap gap-2">
      {sources.map((source) => {
        const key = typeof source === 'string' ? source : source.source_id
        const label = typeof source === 'string' ? source : source.label
        return (
          <span
            key={key}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-hover)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]"
          >
            {label}
          </span>
        )
      })}
    </div>
  )
}
