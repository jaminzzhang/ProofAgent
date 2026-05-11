import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { OverviewPage } from './pages/OverviewPage'
import { RunsListPage } from './pages/RunsListPage'
import { RunDetailPage } from './pages/RunDetailPage'

export function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/runs" element={<RunsListPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>
    </BrowserRouter>
  )
}
