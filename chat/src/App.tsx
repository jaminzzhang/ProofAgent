import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from './router'
import { TopNav } from './components/TopNav'
import { ThemeProvider } from './components/ThemeProvider'

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <div className="h-screen bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200 flex flex-col overflow-hidden">
          <TopNav />
          <div className="flex flex-1 overflow-hidden">
            <main className="flex-1 w-full overflow-y-auto px-8 py-8 relative">
              <div className="max-w-4xl mx-auto pb-12">
                <AppRoutes />
              </div>
            </main>
          </div>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  )
}
