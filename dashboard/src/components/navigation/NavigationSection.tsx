interface NavigationSectionProps {
  title: string
  children?: React.ReactNode
}

export function NavigationSection({ title, children }: NavigationSectionProps) {
  return (
    <div className="mb-6">
      <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h3>
      <div className="space-y-1">
        {children}
      </div>
    </div>
  )
}
