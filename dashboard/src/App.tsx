import { BrowserRouter, useMatch } from 'react-router-dom'
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

  if (agentDetailMatch) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200">
        <AppRoutes />
      </div>
    )
  }

  return (
    <div className="h-screen bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200 flex flex-col overflow-hidden">
      <TopNav />
      <div className="flex flex-1 overflow-hidden max-md:flex-col">
        <Sidebar />
        <main className="flex-1 w-full min-w-0 overflow-y-auto px-8 py-8 relative max-md:px-4 max-md:py-5">
          <div className="mx-auto w-full min-w-0 max-w-6xl pb-12">
            <AppRoutes />
          </div>
        </main>
      </div>
    </div>
  )
}
