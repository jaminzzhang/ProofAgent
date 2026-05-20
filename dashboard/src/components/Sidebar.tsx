import { NavLink, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { 
    to: '/', 
    label: 'Overview',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"/><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"/></svg>
  },
  { 
    to: '/runs', 
    label: 'Runs',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
  },
  {
    to: '/handoffs',
    label: 'Handoffs',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 8h10"/><path d="M7 12h6"/><path d="M5 20l-1.5-3A8 8 0 1 1 12 20z"/></svg>
  },
  { 
    to: '#approvals', 
    label: 'Approvals',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  },
  { 
    to: '#policies', 
    label: 'Policies',
    icon: <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
  },
]

export function Sidebar() {
  const location = useLocation()

  return (
    <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--bg-surface)] flex flex-col overflow-y-auto pt-6 pb-4">
      <nav className="flex-1 px-3 space-y-1" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => {
          const isHash = item.to.startsWith('#')
          const isItemActive = isHash 
            ? location.hash === item.to 
            : (item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)) && location.hash === ''

          return (
            <NavLink
              key={item.label}
              to={item.to}
              className={`group flex items-center gap-3 px-3 py-2 text-[14px] font-medium transition-colors rounded-md ${
                  isItemActive
                    ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                }`
              }
            >
              <span className={`transition-colors ${isItemActive ? 'text-current' : 'text-[var(--text-muted)] group-hover:text-current'}`}>
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      {/* Settings at the bottom */}
      <div className="px-3 mt-auto">
        <NavLink
          to="#settings"
          className={
            `group flex items-center gap-3 px-3 py-2 text-[14px] font-medium transition-colors rounded-md ${
              location.hash === '#settings'
                ? 'bg-[var(--bg-hover)] text-[var(--text-primary)]'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
            }`
          }
        >
          <span className={`transition-colors ${location.hash === '#settings' ? 'text-current' : 'text-[var(--text-muted)] group-hover:text-current'}`}>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
          </span>
          Settings
        </NavLink>
      </div>
    </aside>
  )
}
