import { useEffect, useMemo, useRef, useState } from 'react'
import { createConversation, createRun, fetchConversation } from '../api/client'
import type { CustomerConversation, CustomerRunResponse, CustomerTurn } from '../api/types'
import { FeedbackControl } from '../components/FeedbackControl'
import { ProgressState } from '../components/ProgressState'
import { SourceList } from '../components/SourceList'

type CustomerMode = 'anonymous' | 'CUST-001' | 'CUST-002'

const MODES: Array<{ id: CustomerMode; label: string; customerId: string | null }> = [
  { id: 'anonymous', label: 'Guest', customerId: null },
  { id: 'CUST-001', label: 'Demo 1', customerId: 'CUST-001' },
  { id: 'CUST-002', label: 'Demo 2', customerId: 'CUST-002' },
]

const STARTERS = [
  'What documents are required for inpatient claim reimbursement?',
  'What is my policy status?',
  'What is the status of claim CLM-001?',
]

export function CustomerChatPage() {
  const [mode, setMode] = useState<CustomerMode>('anonymous')
  const [conversation, setConversation] = useState<CustomerConversation | null>(null)
  const [turns, setTurns] = useState<CustomerTurn[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const activeMode = useMemo(() => MODES.find((item) => item.id === mode) ?? MODES[0], [mode])

  useEffect(() => {
    setConversation(null)
    setTurns([])
    setInput('')
    setError(null)
  }, [mode])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length, sending])

  const ensureConversation = async () => {
    if (conversation) return conversation
    const created = await createConversation('insurance_customer_service', activeMode.customerId)
    setConversation(created)
    return created
  }

  const sendQuestion = async (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || sending) return
    setInput('')
    setError(null)
    setSending(true)

    try {
      const activeConversation = await ensureConversation()
      const response = await createRun(activeConversation.conversation_id, trimmed)
      const updated = await fetchConversation(activeConversation.conversation_id)
      setConversation(updated)
      setTurns(updated.turns.length > 0 ? updated.turns : [responseToTurn(trimmed, response)])
    } catch (err) {
      console.error('Customer run failed', err)
      setError('The service is unavailable. Please try again.')
    } finally {
      setSending(false)
    }
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    void sendQuestion(input)
  }

  return (
    <main className="min-h-screen overflow-x-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-[var(--border)] pb-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-normal">Insurance Customer Service</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">Read-only policy and claim support</p>
          </div>
          <div className="grid w-full grid-cols-1 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] p-1 sm:grid-cols-3 md:w-auto">
            {MODES.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setMode(item.id)}
                className={`min-w-0 rounded-md px-2 py-2 text-xs font-semibold transition sm:px-3 ${
                  mode === item.id
                    ? 'bg-[var(--surface)] text-[var(--accent)] shadow-sm'
                    : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </header>

        <section className="grid min-h-0 min-w-0 flex-1 gap-5 py-5 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="flex min-h-[620px] min-w-0 flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)]">
            <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 sm:p-6">
              {turns.length === 0 && !sending ? (
                <div className="flex h-full min-h-[420px] flex-col justify-end gap-3">
                  {STARTERS.map((starter) => (
                    <button
                      key={starter}
                      type="button"
                      onClick={() => void sendQuestion(starter)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-left text-sm font-medium text-[var(--text-primary)] transition hover:border-[var(--accent)]"
                    >
                      {starter}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="space-y-5">
                  {turns.map((turn) => (
                    <article key={turn.turn_id} className="space-y-3">
                      <div className="flex justify-end">
                        <div className="max-w-[82%] rounded-lg bg-[var(--accent)] px-4 py-3 text-sm font-medium text-white">
                          {turn.question}
                        </div>
                      </div>
                      <div className="max-w-[88%] space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <ProgressState state={turn.response_snapshot.progress_state} />
                        </div>
                        <p className="whitespace-pre-wrap text-sm leading-6 text-[var(--text-primary)]">
                          {turn.response_snapshot.message}
                        </p>
                        <SourceList sources={turn.response_snapshot.safe_sources} />
                        {conversation && (
                          <FeedbackControl
                            conversationId={conversation.conversation_id}
                            turnId={turn.turn_id}
                          />
                        )}
                      </div>
                    </article>
                  ))}
                  {sending && (
                    <div className="max-w-[88%] rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-4">
                      <ProgressState state="retrieving_evidence" active />
                    </div>
                  )}
                </div>
              )}
            </div>

            <form onSubmit={handleSubmit} className="border-t border-[var(--border)] p-3 sm:p-4">
              {error && <div className="mb-3 rounded-md bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger)]">{error}</div>}
              <div className="flex gap-3">
                <input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  disabled={sending}
                  placeholder="Ask about a policy, claim, or reimbursement"
                  className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-white px-4 py-3 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-60"
                />
                <button
                  type="submit"
                  disabled={sending || !input.trim()}
                  className="rounded-lg bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Send
                </button>
              </div>
            </form>
          </div>

          <aside className="min-w-0 space-y-4">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">Session</h2>
              <dl className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Customer</dt>
                  <dd className="min-w-0 break-all text-right font-medium">{activeMode.customerId ?? 'Anonymous'}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Agent</dt>
                  <dd className="min-w-0 break-all text-right font-medium">insurance_customer_service</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Turns</dt>
                  <dd className="min-w-0 break-all text-right font-medium">{turns.length}</dd>
                </div>
              </dl>
            </div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">Recent Sources</h2>
              <div className="mt-3">
                <SourceList sources={latestSources(turns)} />
                {latestSources(turns).length === 0 && (
                  <p className="text-sm text-[var(--text-secondary)]">No sources yet</p>
                )}
              </div>
            </div>
          </aside>
        </section>
      </div>
    </main>
  )
}

function responseToTurn(question: string, response: CustomerRunResponse): CustomerTurn {
  return {
    turn_id: response.turn_id,
    run_id: response.run_id,
    question,
    response_snapshot: response,
    created_at: new Date().toISOString(),
  }
}

function latestSources(turns: CustomerTurn[]): string[] {
  const last = turns.at(-1)
  return last?.response_snapshot.safe_sources ?? []
}
