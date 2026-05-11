interface SectionHeaderProps {
  title: string
  count?: number
}

export function SectionHeader({ title, count }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <h2 className="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wider">{title}</h2>
      {count !== undefined && (
        <span className="text-xs font-mono font-medium bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-secondary)] px-2 py-0.5 rounded-full shadow-sm">
          {count}
        </span>
      )}
    </div>
  )
}
