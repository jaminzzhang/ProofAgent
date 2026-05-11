import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from './router'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen bg-[var(--bg-base)]">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar title="Proof Agent Dashboard" />
          <main className="flex-1 overflow-auto p-6">
            <AppRoutes />
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
