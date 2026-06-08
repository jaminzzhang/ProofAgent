import { useTheme } from './ThemeProvider'

interface TopNavProps {
  leading?: React.ReactNode
  title?: React.ReactNode
  subtitle?: React.ReactNode
  status?: React.ReactNode
  showThemeToggle?: boolean
}

export function TopNav({
  leading,
  title = 'Proof Agent',
  subtitle,
  status,
  showThemeToggle = true,
}: TopNavProps) {
  return (
    <header className="h-16 border-b border-[var(--border)] bg-[var(--bg-surface)] flex justify-between items-center px-6 sticky top-0 z-50">
      <div className="flex min-w-0 items-center gap-3">
        {leading}

        {/* Logo Icon */}
        <div className="w-7 h-7 shrink-0 bg-[var(--accent)] text-[var(--accent-fg)] flex items-center justify-center rounded-[4px]">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        </div>
        
        {/* Breadcrumbs */}
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <div className="min-w-0">
            <div className="truncate font-semibold tracking-tight text-[var(--text-primary)]">
              {title}
            </div>
            {subtitle && (
              <div className="mt-0.5 hidden max-w-3xl truncate text-xs text-[var(--text-muted)] md:block">
                {subtitle}
              </div>
            )}
          </div>
          {status}
        </div>
      </div>

      <div className="flex items-center gap-4">
        {showThemeToggle && <ThemeToggleButton />}
      </div>
    </header>
  )
}

function ThemeToggleButton() {
  const { theme, toggleTheme } = useTheme()

  return (
    <button
      onClick={toggleTheme}
      className="p-1.5 rounded-md text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
      aria-label="Toggle Theme"
    >
      {theme === 'light' ? (
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>
      )}
    </button>
  )
}
