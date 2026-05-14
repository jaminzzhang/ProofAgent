import { BrowserRouter, useNavigate, useParams, useLocation } from 'react-router-dom'
import { AppRoutes } from './router'
import { TopNav } from './components/TopNav'
import { ThemeProvider } from './components/ThemeProvider'
import { HistorySidebar } from './components/HistorySidebar'
import { useState, useEffect } from 'react'
import { fetchConversations, updateConversation, deleteConversation } from './api/client'
import type { ConversationRecord } from './api/types'

function Layout() {
  const [conversations, setConversations] = useState<ConversationRecord[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const { conversationId } = useParams()
  const location = useLocation()

  const loadConversations = async () => {
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
    loadConversations()
  }, [])

  useEffect(() => {
    if (!conversationId && !loading && conversations.length > 0 && location.pathname === '/') {
      navigate(`/c/${conversations[0].conversation_id}`, { replace: true })
    }
  }, [conversationId, loading, conversations, location.pathname, navigate])

  const handleNewChat = () => {
    navigate('/new')
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
          navigate(`/c/${updated[0].conversation_id}`, { replace: true })
        } else {
          navigate('/', { replace: true })
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
    <div className="h-screen bg-[var(--bg-base)] text-[var(--text-primary)] transition-colors duration-200 flex flex-col overflow-hidden">
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <HistorySidebar
          conversations={conversations}
          onNewChat={handleNewChat}
          onRename={handleRename}
          onDelete={handleDelete}
          onTogglePin={handleTogglePin}
        />
        <main className="flex-1 w-full overflow-y-auto px-8 py-8 relative">
          <div className="max-w-4xl mx-auto pb-12">
            <AppRoutes onConversationUpdate={loadConversations} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </ThemeProvider>
  )
}
