import type { ReactNode } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  cn,
} from '@proofagent/ui'

interface AgentDetailDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  children: ReactNode
  footer?: ReactNode
  bodyClassName?: string
}

export function AgentDetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  bodyClassName,
}: AgentDetailDrawerProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-auto right-0 top-0 flex h-dvh max-h-dvh w-[92vw] max-w-[92vw] translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-y-0 border-r-0 p-0 shadow-[var(--shadow-lg)] data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right data-[state=closed]:zoom-out-100 data-[state=open]:zoom-in-100 md:w-[67vw] md:max-w-[67vw] sm:rounded-none">
        <header className="shrink-0 border-b border-[var(--border)] px-5 py-4 pr-12 md:px-8">
          <DialogTitle className="text-sm font-semibold text-[var(--text-primary)]">
            {title}
          </DialogTitle>
          <DialogDescription className="mt-1 text-sm text-[var(--text-muted)]">
            {description}
          </DialogDescription>
        </header>
        <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-8', bodyClassName)}>
          {children}
        </div>
        {footer ? (
          <footer className="flex shrink-0 justify-end gap-3 border-t border-[var(--border)] px-5 py-4 md:px-8">
            {footer}
          </footer>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
