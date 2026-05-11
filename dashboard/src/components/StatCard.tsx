interface StatCardProps {
  label: string
  value: string | number
  subtitle?: string
  warning?: boolean
}

export function StatCard({ label, value, subtitle, warning }: StatCardProps) {
  return (
    <div
      className={`rounded-lg p-4 border ${
        warning
          ? 'border-amber-500/30 bg-amber-500/5'
          : 'border-[var(--border)] bg-[var(--bg-surface)]'
      }`}
    >
      <p className="text-xs text-[var(--text-muted)] uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-semibold ${warning ? 'text-amber-400' : 'text-[var(--text-primary)]'}`}>
        {value}
      </p>
      {subtitle && <p className="text-xs text-[var(--text-secondary)] mt-1">{subtitle}</p>}
    </div>
  )
}
