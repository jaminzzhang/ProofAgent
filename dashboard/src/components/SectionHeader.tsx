interface SectionHeaderProps {
  title: string
  count?: number
}

export function SectionHeader({ title, count }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <h2 className="text-sm font-semibold text-[var(--text-secondary)] uppercase tracking-wide">{title}</h2>
      {count !== undefined && (
        <span className="text-xs bg-[var(--bg-elevated)] text-[var(--text-muted)] px-1.5 py-0.5 rounded">
          {count}
        </span>
      )}
    </div>
  )
}
