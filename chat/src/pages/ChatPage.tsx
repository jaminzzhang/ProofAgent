import { useState, useEffect, useRef } from 'react'
import { fetchConversation, createConversationRun, createConversation } from '../api/client'
import type { ConversationRecord } from '../api/types'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useParams, useLocation, useNavigate } from 'react-router-dom'

const SYNTHETIC_NEW_CHAT: ConversationRecord = {
  conversation_id: '',
  agent_id: 'enterprise_qa',
  title: null,
  pinned: false,
  created_at: '',
  updated_at: '',
  turns: [],
}

export function ChatPage({ onUpdate }: { onUpdate?: () => void }) {
  const { conversationId } = useParams<{ conversationId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const isNewChat = location.pathname === '/new'
  const [conversation, setConversation] = useState<ConversationRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  // Load backend conversation when conversationId changes
  useEffect(() => {
    if (conversationId) {
      setLoading(true)
      setError(null)
      setConversation(null)
      fetchConversation(conversationId)
        .then(setConversation)
        .catch(() => {
          setError('Failed to load conversation. It may have been deleted or the server is unavailable.')
        })
        .finally(() => setLoading(false))
    } else if (isNewChat) {
      setConversation(SYNTHETIC_NEW_CHAT)
      setLoading(false)
      setError(null)
    } else {
      setLoading(false)
      setConversation(null)
    }
  }, [conversationId, isNewChat])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [conversation?.turns.length, sending])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim()) return
    if (!conversation && !isNewChat) return

    const q = input
    setInput('')
    setSending(true)

    try {
      // Lazy creation: create backend conversation on first send
      let activeConversationId = conversation?.conversation_id
      if (isNewChat && !activeConversationId) {
        const newConv = await createConversation('enterprise_qa')
        activeConversationId = newConv.conversation_id
      }

      const result = await createConversationRun(activeConversationId!, q)
      onUpdate?.()

      // If this was a new chat, navigate to the real conversation
      if (isNewChat) {
        navigate(`/c/${activeConversationId}`, { replace: true })
        return
      }

      // Optimistically append the new turn
      setConversation((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          updated_at: new Date().toISOString(),
          turns: [
            ...prev.turns,
            {
              turn_id: result.turn_id || '',
              run_id: result.run_id,
              agent_id: result.agent_id,
              question: q,
              final_output: result.final_output,
              outcome: result.outcome,
              created_at: new Date().toISOString(),
              context_admission: result.context_admission || {
                admitted: false,
                turn_count: 0,
                included_turn_ids: [],
                summary: '',
                char_count: 0,
                max_turns: 3,
              },
              evidence: result.evidence || [],
              approval_state: result.approval_state || null,
              links: result.links,
            },
          ],
        }
      })
    } catch (err) {
      console.error('Failed to send message', err)
    } finally {
      setSending(false)
    }
  }

  // No conversationId and not new chat: show landing state
  if (!conversationId && !isNewChat) {
    return (
      <div className="flex flex-col h-[calc(100vh-160px)] max-w-4xl mx-auto px-4">
        <div className="flex-1 flex flex-col items-center justify-center text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-[var(--bg-hover)] flex items-center justify-center text-2xl">
            💬
          </div>
          <div>
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">Assisted Chat</h2>
            <p className="text-sm text-[var(--text-muted)] mt-1 max-w-[280px]">
              Select a conversation from the sidebar or start a new one.
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="py-12 flex justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col h-[calc(100vh-160px)] max-w-4xl mx-auto px-4">
        <div className="flex-1 flex flex-col items-center justify-center text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center text-2xl">
            ⚠️
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--text-primary)]">Unable to Load Conversation</h2>
            <p className="text-sm text-[var(--text-muted)] mt-1 max-w-[320px]">{error}</p>
          </div>
          <button
            onClick={() => {
              setError(null)
              setLoading(true)
              fetchConversation(conversationId!)
                .then(setConversation)
                .catch(() => {
                  setError('Failed to load conversation. It may have been deleted or the server is unavailable.')
                })
                .finally(() => setLoading(false))
            }}
            className="px-4 py-2 bg-[var(--accent)] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-all"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!conversation) {
    return null
  }

  return (
    <div className="flex flex-col h-[calc(100vh-160px)] max-w-4xl mx-auto px-4">
      <div className="flex justify-between items-end mb-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Assisted Chat</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">Operator-facing governed question answering.</p>
        </div>
      </div>

      <div
        className="flex-1 overflow-y-auto p-6 space-y-8 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl shadow-sm custom-scrollbar"
        ref={scrollRef}
      >
        {conversation.turns.length === 0 && !sending && (
          <div className="h-full flex flex-col items-center justify-center text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-[var(--bg-hover)] flex items-center justify-center text-2xl">
              👋
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">Start a Conversation</h3>
              <p className="text-xs text-[var(--text-muted)] mt-1 max-w-[240px]">
                Ask the Insurance Service QA agent anything about policies or processes.
              </p>
            </div>
          </div>
        )}

        {conversation.turns.map((turn) => (
          <div key={turn.turn_id} className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
            {/* User Question */}
            <div className="flex justify-end">
              <div className="bg-[var(--accent)] text-white px-4 py-2.5 rounded-2xl rounded-tr-sm max-w-[80%] shadow-sm">
                <p className="text-sm font-medium">{turn.question}</p>
              </div>
            </div>

            {/* Assistant Response */}
            <div className="flex justify-start">
              <div className="bg-[var(--bg-elevated)] p-5 rounded-2xl rounded-tl-sm border border-[var(--border)] max-w-[90%] space-y-4 shadow-sm">
                <div className="text-sm leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap">
                  {turn.final_output || <span className="italic text-[var(--text-muted)]">No output generated.</span>}
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-3 border-t border-[var(--border)]">
                  <OutcomeBadge outcome={turn.outcome} />
                  {turn.evidence.length > 0 && (
                    <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-bold">
                      {turn.evidence.length} Evidence {turn.evidence.length === 1 ? 'Source' : 'Sources'}
                    </span>
                  )}
                  <div className="flex gap-3 ml-auto">
                    <a
                      href={`http://localhost:5173/runs/${turn.run_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[11px] font-bold uppercase tracking-tight text-[var(--accent)] hover:underline"
                    >
                      Audit Trace
                    </a>
                    <a
                      href={turn.links.receipt}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[11px] font-bold uppercase tracking-tight text-[var(--accent)] hover:underline"
                    >
                      Receipt
                    </a>
                  </div>
                </div>

                {turn.outcome === 'WAITING_FOR_APPROVAL' && (
                  <div className="flex gap-2 pt-1">
                    <a
                      href={`http://localhost:5173/runs/${turn.run_id}#approval`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-4 py-1.5 bg-blue-600 text-white text-[11px] font-bold uppercase tracking-wider rounded-md hover:bg-blue-700 transition-colors inline-block"
                    >
                      Review Approval Request
                    </a>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start animate-pulse">
            <div className="bg-[var(--bg-elevated)] p-4 rounded-2xl rounded-tl-sm border border-[var(--border)] flex items-center gap-3">
              <div className="flex gap-1">
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-xs text-[var(--text-muted)] font-medium">Harness Executing...</span>
            </div>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="mt-6 flex gap-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your question for the Assistant..."
          disabled={sending || loading}
          className="flex-1 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl px-5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)] disabled:opacity-50 shadow-sm transition-all"
        />
        <button
          type="submit"
          disabled={sending || loading || !input.trim()}
          className="bg-[var(--accent)] text-white px-8 py-3 rounded-xl text-sm font-bold uppercase tracking-wider hover:opacity-90 disabled:opacity-50 transition-all shadow-md active:scale-95"
        >
          Ask
        </button>
      </form>
    </div>
  )
}
