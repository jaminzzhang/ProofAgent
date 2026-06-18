import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { ChatShell } from '../../chat-core/ChatShell'
import type { ChatTurnView } from '../../chat-core/types'
import { AgentSelectionPanel } from '../../components/AgentSelectionPanel'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useLocale } from '../../i18n/locale'
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

const STARTERS: Array<{ question: string; labelKey: string; fallback: string }> = [
  {
    question: 'What documents are required for inpatient claim reimbursement?',
    labelKey: 'customer.starter.inpatientClaim',
    fallback: 'What documents are required for inpatient claim reimbursement?',
  },
  {
    question: 'What is my policy status?',
    labelKey: 'customer.starter.policyStatus',
    fallback: 'What is my policy status?',
  },
  {
    question: 'What is the status of claim CLM-001?',
    labelKey: 'customer.starter.claimStatus',
    fallback: 'What is the status of claim CLM-001?',
  },
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
  const [allowUntrustedWebSupplement, setAllowUntrustedWebSupplement] = useState(false)
  const { t } = useLocale()

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
        setError(t('customer.loadConversationError'))
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
      .catch(() => setAgentsError(t('customer.loadAgentsError')))
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
      throw new Error(t('customer.noAgentError'))
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
      const response = await createCustomerRun(activeConversation.conversation_id, trimmed, {
        allowUntrustedWebSupplement,
      })
      const updated = await fetchCustomerConversation(activeConversation.conversation_id)
      setConversation(updated)
      setTurns(updated.turns.length > 0 ? updated.turns : [responseToTurn(trimmed, response)])
    } catch (err) {
      console.error('Customer run failed', err)
      setInput(question)
      setError(t('customer.sendError'))
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
        title={t('customer.chooseAgentTitle')}
        description={t('customer.choosePublishedAgentDescription')}
        agents={[]}
        emptyTitle={t('customer.unableLoadAgents')}
        emptyDescription={agentsError}
        onSelect={() => undefined}
      />
    )
  }

  if (!routeConversationId && !selectedAgent) {
    return (
      <AgentSelectionPanel
        title={t('customer.chooseAgentTitle')}
        description={t('customer.chooseAgentDescription')}
        agents={agentId ? [] : agents}
        unavailableAgentId={agentId}
        emptyTitle={t('customer.noAgentsTitle')}
        emptyDescription={
          agentId
            ? t('customer.unpublishedAgent')
            : t('customer.noAgentsDescription')
        }
        onSelect={(nextAgentId) => navigate(`/customer/agents/${nextAgentId}`)}
      />
    )
  }

  return (
    <ChatShell
      title={t('customer.title')}
      subtitle={selectedAgent?.display_name ?? t('customer.defaultSubtitle')}
      turns={turnViews}
      inputValue={input}
      onInputChange={setInput}
      onSubmit={() => void sendQuestion(input)}
      sending={sending}
      untrustedWebSupplementToggle={{
        checked: allowUntrustedWebSupplement,
        onChange: setAllowUntrustedWebSupplement,
      }}
      placeholder={t('customer.placeholder')}
      submitLabel={t('customer.submit')}
      emptyTitle={t('customer.emptyTitle')}
      emptyDescription={t('customer.emptyDescription')}
      error={error}
      starters={STARTERS.map((starter) => ({
        label: t(starter.labelKey, starter.fallback),
        onSelect: () => void sendQuestion(starter.question),
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
