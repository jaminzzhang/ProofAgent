import { useState, useEffect, useRef } from 'react'
import { createConversation, fetchConversation, createConversationRun } from '../api/client'
import type { ConversationRecord, ConversationTurn } from '../api/types'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { Link } from 'react-router-dom'

export function ChatPage() {
  const [conversation, setConversation] = useState<ConversationRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const createNewConversation = () => {
    setLoading(true)
    createConversation('enterprise_qa')
      .then((data) => {
        setConversation(data)
        localStorage.setItem('proof_agent_conversation_id', data.conversation_id)
      })
      .catch((err) => console.error('Failed to create conversation', err))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    const conversationId = localStorage.getItem('proof_agent_conversation_id')
    if (conversationId) {
      fetchConversation(conversationId)
        .then(setConversation)
        .catch(() => {
          createNewConversation()
        })
        .finally(() => setLoading(false))
    } else {
      createNewConversation()
    }
  }, [])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [conversation?.turns.length, sending])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || !conversation) return

    const q = input
    setInput('')
    setSending(true)

    try {
      await createConversationRun(conversation.conversation_id, q)
      const updated = await fetchConversation(conversation.conversation_id)
      setConversation(updated)
    } catch (err) {
      console.error('Failed to send message', err)
    } finally {
      setSending(false)
    }
  }

  const handleApproval = async (turn: ConversationTurn, approved: boolean) => {
    if (!conversation) return
    setSending(true)
    try {
      await createConversationRun(conversation.conversation_id, turn.question, approved)
      const updated = await fetchConversation(conversation.conversation_id)
      setConversation(updated)
    } catch (err) {
      console.error('Failed to send approval', err)
    } finally {
      setSending(false)
    }
  }

  if (loading && !conversation) {
    return (
      <div className="py-12 flex justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-[calc(100vh-160px)] max-w-4xl mx-auto px-4">
      <div className="flex justify-between items-end mb-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Assisted Chat</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">Operator-facing governed question answering.</p>
        </div>
        <button
          onClick={createNewConversation}
          className="text-xs font-medium text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors border border-[var(--border)] px-3 py-1.5 rounded-md hover:bg-[var(--bg-hover)]"
        >
          New Chat
        </button>
      </div>

      <div
        className="flex-1 overflow-y-auto p-6 space-y-8 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl shadow-sm custom-scrollbar"
        ref={scrollRef}
      >
        {conversation?.turns.length === 0 && !sending && (
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

        {conversation?.turns.map((turn) => (
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
                    <Link
                      to={`/runs/${turn.run_id}`}
                      className="text-[11px] font-bold uppercase tracking-tight text-[var(--accent)] hover:underline"
                    >
                      Audit Trace
                    </Link>
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
                    <button
                      onClick={() => handleApproval(turn, true)}
                      disabled={sending}
                      className="px-4 py-1.5 bg-emerald-600 text-white text-[11px] font-bold uppercase tracking-wider rounded-md hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                    >
                      Approve Execution
                    </button>
                    <button
                      onClick={() => handleApproval(turn, false)}
                      disabled={sending}
                      className="px-4 py-1.5 bg-red-600 text-white text-[11px] font-bold uppercase tracking-wider rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
                    >
                      Deny
                    </button>
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
