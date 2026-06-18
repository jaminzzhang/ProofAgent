import { cn } from '@proofagent/ui'

interface NavigationSectionProps {
  title: string
  children?: React.ReactNode
  className?: string
}

export function NavigationSection({ title, children, className }: NavigationSectionProps) {
  return (
    <div className={cn('mb-5', className)}>
      <h3 className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </h3>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}
