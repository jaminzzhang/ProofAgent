import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ChatShell } from '../../chat-core/ChatShell'
import type { ChatTurnView } from '../../chat-core/types'
import type {
  CustomerConversation,
  CustomerRunProgressState,
  CustomerRunResponse,
  CustomerSafeSource,
  CustomerTurn,
} from '../../api/types'
import {
  createCustomerConversation,
  createCustomerRun,
  fetchCustomerConversation,
  normalizeCustomerTurn,
} from './customerAdapter'
import { CustomerSidebar, CUSTOMER_MODES, type CustomerMode } from './CustomerSidebar'
import { FeedbackControl } from './FeedbackControl'
import { ProgressState } from './ProgressState'
import { SourceList } from './SourceList'

const STARTERS = [
  'What documents are required for inpatient claim reimbursement?',
  'What is my policy status?',
  'What is the status of claim CLM-001?',
]

export function CustomerChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [mode, setMode] = useState<CustomerMode>('anonymous')
  const [conversation, setConversation] = useState<CustomerConversation | null>(null)
  const [turns, setTurns] = useState<CustomerTurn[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const activeMode = useMemo(
    () => CUSTOMER_MODES.find((item) => item.id === mode) ?? CUSTOMER_MODES[0],
    [mode],
  )

  useEffect(() => {
    if (!conversationId) return
    setError(null)
    fetchCustomerConversation(conversationId)
      .then((record) => {
        setConversation(record)
        setTurns(record.turns)
      })
      .catch(() => {
        setError('The conversation is unavailable. Please start a new session.')
      })
  }, [conversationId])

  const turnViews = useMemo(() => turns.map(normalizeCustomerTurn), [turns])

  const handleModeChange = (nextMode: CustomerMode) => {
    setMode(nextMode)
    setConversation(null)
    setTurns([])
    setInput('')
    setError(null)
    navigate('/customer', { replace: true })
  }

  const ensureConversation = async () => {
    if (conversation) return conversation
    const created = await createCustomerConversation('insurance_customer_service', activeMode.customerId)
    setConversation(created)
    navigate(`/customer/c/${created.conversation_id}`, { replace: true })
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
      const response = await createCustomerRun(activeConversation.conversation_id, trimmed)
      const updated = await fetchCustomerConversation(activeConversation.conversation_id)
      setConversation(updated)
      setTurns(updated.turns.length > 0 ? updated.turns : [responseToTurn(trimmed, response)])
    } catch (err) {
      console.error('Customer run failed', err)
      setInput(question)
      setError('The service is unavailable. Please try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <ChatShell
      title="Customer Chat"
      subtitle="Customer-safe service chat for policy and claim support."
      turns={turnViews}
      inputValue={input}
      onInputChange={setInput}
      onSubmit={() => void sendQuestion(input)}
      sending={sending}
      placeholder="Ask about a policy, claim, or reimbursement"
      submitLabel="Send"
      emptyTitle="Start a Conversation"
      emptyDescription="Ask a customer-safe service question."
      error={error}
      starters={STARTERS.map((starter) => ({
        label: starter,
        onSelect: () => void sendQuestion(starter),
      }))}
      sidePanel={
        <CustomerSidebar
          mode={mode}
          onModeChange={handleModeChange}
          turnCount={turns.length}
          latestSources={latestSources(turnViews)}
        />
      }
      renderAssistantMeta={(turn) => (
        <div className="flex flex-wrap items-center gap-2">
          <ProgressState state={(turn.assistant.progressState ?? 'completed') as CustomerRunProgressState} />
        </div>
      )}
      renderAssistantActions={(turn) => (
        <div className="space-y-3">
          <SourceList sources={turn.assistant.sources ?? []} />
          {conversation && (
            <FeedbackControl
              conversationId={conversation.conversation_id}
              turnId={turn.id}
            />
          )}
        </div>
      )}
      sendingLabel={<ProgressState state="retrieving_evidence" active />}
    />
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

function latestSources(turns: ChatTurnView[]): Array<string | CustomerSafeSource> {
  const last = turns.at(-1)
  return last?.assistant.sources ?? []
}
