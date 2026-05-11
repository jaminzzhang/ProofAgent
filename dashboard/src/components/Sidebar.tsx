import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/runs', label: 'Runs' },
  { to: '#approvals', label: 'Approvals' },
  { to: '#policies', label: 'Policies' },
  { to: '#configuration', label: 'Configuration' },
  { to: '#compare', label: 'Compare' },
]

export function Sidebar() {
  return (
    <aside className="w-48 shrink-0 border-r border-[var(--border)] bg-[var(--bg-surface)] flex flex-col">
      <div className="p-4 border-b border-[var(--border)]">
        <h1 className="text-sm font-bold text-[var(--text-primary)]">Proof Agent</h1>
        <p className="text-xs text-[var(--text-muted)]">Dashboard</p>
      </div>
      <nav className="flex-1 py-2" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.label}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `block px-4 py-2 text-sm transition-colors ${
                isActive
                  ? 'text-[var(--accent)] bg-[var(--bg-hover)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
