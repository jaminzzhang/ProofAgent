import { BrowserRouter, matchPath, useLocation, useNavigate } from 'react-router-dom'
import { ToasterProvider } from '@proofagent/ui'
import { AppRoutes } from './router'
import { TopNav } from './components/TopNav'
import { ThemeProvider } from './components/ThemeProvider'
import { HistorySidebar } from './components/HistorySidebar'
import { useState, useEffect } from 'react'
import { fetchConversations, updateConversation, deleteConversation } from './api/client'
import type { ConversationRecord } from './api/types'
import { LocaleProvider } from './i18n/locale'

function Layout() {
  const [conversations, setConversations] = useState<ConversationRecord[]>([])
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const isOperatorRoute = location.pathname.startsWith('/operator')
  const operatorMatch = matchPath('/operator/c/:conversationId', location.pathname)
  const conversationId = operatorMatch?.params.conversationId

  const loadConversations = async () => {
    setLoading(true)
    try {
      const data = await fetchConversations()
      setConversations(data)
      return data
    } catch (err) {
      console.error('Failed to fetch conversations', err)
      return []
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOperatorRoute) {
      void loadConversations()
    } else {
      setConversations([])
      setLoading(false)
    }
  }, [isOperatorRoute])

  useEffect(() => {
    if (!conversationId && !loading && conversations.length > 0 && location.pathname === '/operator') {
      navigate(`/operator/c/${conversations[0].conversation_id}`, { replace: true })
    }
  }, [conversationId, loading, conversations, location.pathname, navigate])

  const handleNewChat = () => {
    navigate('/operator/new')
  }

  const handleRename = async (id: string, title: string) => {
    try {
      await updateConversation(id, { title: title || null })
      await loadConversations()
    } catch (err) {
      console.error('Failed to rename conversation', err)
    }
  }

  const handleDelete = async (id: string) => {
    const wasActive = conversationId === id
    try {
      await deleteConversation(id)
      const updated = await fetchConversations()
      setConversations(updated)
      if (wasActive) {
        if (updated.length > 0) {
          navigate(`/operator/c/${updated[0].conversation_id}`, { replace: true })
        } else {
          navigate('/operator', { replace: true })
        }
      }
    } catch (err) {
      console.error('Failed to delete conversation', err)
    }
  }

  const handleTogglePin = async (id: string, pinned: boolean) => {
    try {
      await updateConversation(id, { pinned })
      await loadConversations()
    } catch (err) {
      console.error('Failed to update pin state', err)
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200">
      <TopNav />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {isOperatorRoute && (
          <HistorySidebar
            conversations={conversations}
            onNewChat={handleNewChat}
            onRename={handleRename}
            onDelete={handleDelete}
            onTogglePin={handleTogglePin}
            routePrefix="/operator"
          />
        )}
        {/* Chat fills available height; ChatShell owns its own max-width + scroll */}
        <main className="min-h-0 w-full flex-1 overflow-hidden py-6">
          <AppRoutes onConversationUpdate={loadConversations} />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <LocaleProvider>
        <ToasterProvider>
          <BrowserRouter>
            <Layout />
          </BrowserRouter>
        </ToasterProvider>
      </LocaleProvider>
    </ThemeProvider>
  )
}
