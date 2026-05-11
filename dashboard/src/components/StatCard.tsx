interface StatCardProps {
  label: string
  value: string | number
  subtitle?: string
  warning?: boolean
}

export function StatCard({ label, value, subtitle, warning }: StatCardProps) {
  return (
    <div
      className={`rounded-lg p-6 border transition-colors duration-200 ${
        warning
          ? 'border-[var(--warning)] bg-[var(--warning-bg)]'
          : 'border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--border-hover)]'
      }`}
    >
      <p className="text-sm font-medium text-[var(--text-secondary)] mb-2">{label}</p>
      <p className={`text-3xl font-semibold tracking-tight ${warning ? 'text-[var(--warning)]' : 'text-[var(--text-primary)]'}`}>
        {value}
      </p>
      {subtitle && <p className="text-sm text-[var(--text-muted)] mt-2 font-medium">{subtitle}</p>}
    </div>
  )
}
