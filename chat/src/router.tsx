import { Routes, Route, Navigate } from 'react-router-dom'
import { ModeSelectionPage } from './pages/ModeSelectionPage'
import { CustomerChatPage } from './modes/customer/CustomerChatPage'
import { OperatorChatPage } from './modes/operator/OperatorChatPage'

export { Routes, Route }

export function AppRoutes({ onConversationUpdate }: { onConversationUpdate?: () => void }) {
  return (
    <Routes>
      <Route path="/" element={<ModeSelectionPage />} />
      <Route path="/operator" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/operator/new" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/operator/c/:conversationId" element={<OperatorChatPage onUpdate={onConversationUpdate} />} />
      <Route path="/customer" element={<CustomerChatPage />} />
      <Route path="/customer/new" element={<CustomerChatPage />} />
      <Route path="/customer/c/:conversationId" element={<CustomerChatPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
