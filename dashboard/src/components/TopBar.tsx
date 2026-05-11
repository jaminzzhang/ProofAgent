interface TopBarProps {
  title: string
}

export function TopBar({ title }: TopBarProps) {
  return (
    <header className="h-12 border-b border-[var(--border)] bg-[var(--bg-surface)] flex items-center px-6">
      <h1 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h1>
    </header>
  )
}
