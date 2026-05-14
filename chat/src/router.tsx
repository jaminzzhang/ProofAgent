import { Routes, Route } from 'react-router-dom'
import { ChatPage } from './pages/ChatPage'

export { Routes, Route }

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
    </Routes>
  )
}
