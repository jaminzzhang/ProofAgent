import { NavLink, useLocation } from 'react-router-dom'

interface NavigationItemProps {
  to: string
  label: string
  icon: React.ReactNode
}

export function NavigationItem({ to, label, icon }: NavigationItemProps) {
  const location = useLocation()
  const isHash = to.startsWith('#')
  const isActive = isHash
    ? location.hash === to
    : (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)) && location.hash === ''

  return (
    <NavLink
      to={to}
      className={`group flex items-center gap-3 px-3 py-2 text-[14px] font-medium transition-colors rounded-md ${
        isActive
          ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
      }`}
    >
      <span className={`transition-colors ${isActive ? 'text-current' : 'text-[var(--text-muted)] group-hover:text-current'}`}>
        {icon}
      </span>
      {label}
    </NavLink>
  )
}
