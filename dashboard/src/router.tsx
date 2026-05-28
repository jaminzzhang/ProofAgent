import { Routes, Route } from 'react-router-dom'
import { OverviewPage } from './pages/OverviewPage'
import { RunsListPage } from './pages/RunsListPage'
import { RunDetailPage } from './pages/RunDetailPage'
import { HandoffsPage } from './pages/HandoffsPage'
import { AgentsPage } from './pages/AgentsPage'
import { AgentDetailPage } from './pages/AgentDetailPage'
import { PoliciesPage } from './pages/PoliciesPage'
import { ToolsPage } from './pages/ToolsPage'
import { KnowledgePage } from './pages/KnowledgePage'

export { Routes, Route }

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/agents" element={<AgentsPage />} />
      <Route path="/agents/:agentId/drafts/:draftId" element={<AgentDetailPage />} />
      <Route path="/policies" element={<PoliciesPage />} />
      <Route path="/tools" element={<ToolsPage />} />
      <Route path="/knowledge" element={<KnowledgePage />} />
      <Route path="/runs" element={<RunsListPage />} />
      <Route path="/handoffs" element={<HandoffsPage />} />
      <Route path="/runs/:runId" element={<RunDetailPage />} />
    </Routes>
  )
}
