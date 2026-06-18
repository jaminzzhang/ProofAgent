import { NavLink, useLocation } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@proofagent/ui'

interface NavigationItemProps {
  to: string
  label: string
  /** lucide icon component */
  icon: LucideIcon
}

/**
 * Sidebar nav item with a single, unified active idiom used across the app:
 * subtle accent-tinted background + left 2px accent indicator. Replaces the
 * former hover-bg-only treatment so it matches the secondary sidebar.
 */
export function NavigationItem({ to, label, icon: Icon }: NavigationItemProps) {
  const location = useLocation()
  const isHash = to.startsWith('#')
  const isActive = isHash
    ? location.hash === to
    : (to === '/'
        ? location.pathname === '/'
        : location.pathname.startsWith(to)) && location.hash === ''

  return (
    <NavLink
      to={to}
      className={cn(
        'group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
        isActive
          ? 'bg-[var(--accent-subtle)] text-[var(--text-primary)]'
          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
      )}
    >
      {/* left accent indicator on active */}
      {isActive && (
        <span
          className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full bg-[var(--accent)]"
          aria-hidden="true"
        />
      )}
      <Icon
        size={16}
        strokeWidth={2}
        className={cn(
          'shrink-0 transition-colors',
          isActive
            ? 'text-[var(--text-primary)]'
            : 'text-[var(--text-muted)] group-hover:text-current',
        )}
      />
      <span className="truncate">{label}</span>
    </NavLink>
  )
}
