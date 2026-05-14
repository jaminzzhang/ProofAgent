import { Routes, Route, Navigate } from 'react-router-dom'
import { ChatPage } from './pages/ChatPage'

export { Routes, Route }

export function AppRoutes({ onConversationUpdate }: { onConversationUpdate?: () => void }) {
  return (
    <Routes>
      <Route path="/" element={<ChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/new" element={<ChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/c/:conversationId" element={<ChatPage onUpdate={onConversationUpdate} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
