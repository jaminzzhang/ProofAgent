import { useEffect, useState } from 'react'
import { BrowserRouter, useLocation, useMatch } from 'react-router-dom'
import { Menu } from 'lucide-react'
import { ToasterProvider } from '@proofagent/ui'
import { AppRoutes } from './router'
import { TopNav } from './components/TopNav'
import { Sidebar } from './components/Sidebar'
import { ThemeProvider } from './components/ThemeProvider'
import { LocaleProvider } from './i18n/locale'

export default function App() {
  return (
    <ThemeProvider>
      <LocaleProvider>
        <ToasterProvider>
          <BrowserRouter>
            <AppFrame />
          </BrowserRouter>
        </ToasterProvider>
      </LocaleProvider>
    </ThemeProvider>
  )
}

function AppFrame() {
  const agentDetailMatch = useMatch('/agents/:agentId/drafts/:draftId')
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname, location.search, location.hash])

  if (agentDetailMatch) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200">
        <AppRoutes />
      </div>
    )
  }

  return (
    <div className="h-screen bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200 flex flex-col overflow-hidden">
      <TopNav
        leading={
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMenuOpen(true)}
            className="rounded-md p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] md:hidden"
          >
            <Menu size={18} />
          </button>
        }
      />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
        <main className="flex-1 w-full min-w-0 overflow-y-auto px-8 py-8 relative max-md:px-4 max-md:py-5">
          <div className="mx-auto w-full min-w-0 max-w-7xl pb-12">
            <AppRoutes />
          </div>
        </main>
      </div>
    </div>
  )
}
