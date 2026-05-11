import { Router } from './router'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'

export default function App() {
  return (
    <div className="flex h-screen bg-[var(--bg-base)]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar title="Proof Agent Dashboard" />
        <main className="flex-1 overflow-auto p-6">
          <Router />
        </main>
      </div>
    </div>
  )
}
