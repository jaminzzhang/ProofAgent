import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { ChatShell } from '../../chat-core/ChatShell'
import type { ChatTurnView } from '../../chat-core/types'
import { AgentSelectionPanel } from '../../components/AgentSelectionPanel'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import type {
  CustomerConversation,
  CustomerRunProgressState,
  CustomerRunResponse,
  CustomerSafeSource,
  CustomerTurn,
  PublishedAgentDirectoryEntry,
} from '../../api/types'
import {
  createCustomerConversation,
  createCustomerRun,
  fetchCustomerAgents,
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
  const { conversationId, agentId } = useParams<{ conversationId: string; agentId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const routeConversationId = location.pathname.startsWith('/customer/c/') ? conversationId : undefined
  const [mode, setMode] = useState<CustomerMode>('anonymous')
  const [agents, setAgents] = useState<PublishedAgentDirectoryEntry[]>([])
  const [agentsLoading, setAgentsLoading] = useState(false)
  const [agentsError, setAgentsError] = useState<string | null>(null)
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
    if (!routeConversationId) return
    setError(null)
    fetchCustomerConversation(routeConversationId)
      .then((record) => {
        setConversation(record)
        setTurns(record.turns)
      })
      .catch(() => {
        setError('The conversation is unavailable. Please start a new session.')
      })
  }, [routeConversationId])

  useEffect(() => {
    if (routeConversationId) {
      setAgents([])
      setAgentsLoading(false)
      setAgentsError(null)
      return
    }
    setAgentsLoading(true)
    setAgentsError(null)
    fetchCustomerAgents()
      .then((response) => setAgents(response.data))
      .catch(() => setAgentsError('Failed to load Customer-Facing Published Agents.'))
      .finally(() => setAgentsLoading(false))
  }, [routeConversationId])

  const selectedAgent = useMemo(() => {
    if (conversation) {
      return {
        agent_id: conversation.agent_id,
        display_name: conversation.agent_id,
        purpose: '',
        agent_version_id: null,
        customer_facing: true,
      }
    }
    if (routeConversationId) return null
    if (agentId) return agents.find((agent) => agent.agent_id === agentId) ?? null
    return agents.length === 1 ? agents[0] : null
  }, [agentId, agents, conversation, routeConversationId])

  const turnViews = useMemo(() => turns.map(normalizeCustomerTurn), [turns])

  const handleModeChange = (nextMode: CustomerMode) => {
    setMode(nextMode)
    setConversation(null)
    setTurns([])
    setInput('')
    setError(null)
    navigate(agentId ? `/customer/agents/${agentId}` : '/customer', { replace: true })
  }

  const ensureConversation = async () => {
    if (conversation) return conversation
    if (!selectedAgent) {
      throw new Error('No Customer-Facing Published Agent selected.')
    }
    const created = await createCustomerConversation(selectedAgent.agent_id, activeMode.customerId)
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

  if (!routeConversationId && agentsLoading) {
    return (
      <div className="py-12 flex justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!routeConversationId && agentsError) {
    return (
      <AgentSelectionPanel
        title="Choose a Customer-Facing Published Agent"
        description="Select a Published Agent before starting customer chat."
        agents={[]}
        emptyTitle="Unable to load Customer-Facing Published Agents"
        emptyDescription={agentsError}
        onSelect={() => undefined}
      />
    )
  }

  if (!routeConversationId && !selectedAgent) {
    return (
      <AgentSelectionPanel
        title="Choose a Customer-Facing Published Agent"
        description="Select a Customer-Facing Published Agent before starting customer chat."
        agents={agentId ? [] : agents}
        unavailableAgentId={agentId}
        emptyTitle="No Customer-Facing Published Agents are available"
        emptyDescription={
          agentId
            ? 'This Agent is not published for customer chat. Publish a customer-facing Agent before opening chat.'
            : 'Import an Agent template, validate it, and publish a customer-facing Agent in the Dashboard first.'
        }
        onSelect={(nextAgentId) => navigate(`/customer/agents/${nextAgentId}`)}
      />
    )
  }

  return (
    <ChatShell
      title="Customer Chat"
      subtitle={selectedAgent?.display_name ?? 'Customer-safe service chat for policy and claim support.'}
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
          agentLabel={selectedAgent?.display_name ?? conversation?.agent_id ?? ''}
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
