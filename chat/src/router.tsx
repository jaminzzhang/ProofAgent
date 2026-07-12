import { Routes, Route, Navigate } from 'react-router-dom'
import { ModeSelectionPage } from './pages/ModeSelectionPage'
import { OperatorChatPage } from './modes/operator/OperatorChatPage'

export { Routes, Route }

export function AppRoutes({ onConversationUpdate }: { onConversationUpdate?: () => void }) {
  return (
    <Routes>
      <Route path="/" element={<ModeSelectionPage />} />
      <Route path="/operator" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/operator/new" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/operator/agents/:agentId/new" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/operator/c/:conversationId" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
