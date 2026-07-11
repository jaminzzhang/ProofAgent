import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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

interface CustomerRouteHandoff {
  agentId: string
  conversationId: string
  customerId: string | null
  fallbackTurn: CustomerTurn
}

class CustomerBindingError extends Error {}

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
  const requestGenerationRef = useRef(0)
  const routeHandoffRef = useRef<CustomerRouteHandoff | null>(null)
  const translateRef = useRef(t)
  translateRef.current = t

  const activeMode = useMemo(
    () => CUSTOMER_MODES.find((item) => item.id === mode) ?? CUSTOMER_MODES[0],
    [mode],
  )

  useLayoutEffect(() => {
    requestGenerationRef.current += 1
    const routeHandoff =
      routeConversationId
      && routeHandoffRef.current?.conversationId === routeConversationId
        ? routeHandoffRef.current
        : null
    if (!routeHandoff) {
      routeHandoffRef.current = null
      setConversation(null)
      setTurns([])
    }
    setInput('')
    setSending(false)
    setError(null)
    setMode(
      routeConversationId
        ? customerModeFor(routeHandoff?.customerId ?? null) ?? 'anonymous'
        : customerModeFromRouteState(location.state) ?? 'anonymous',
    )
  }, [location.key, location.pathname, routeConversationId])

  useEffect(() => {
    return () => {
      requestGenerationRef.current += 1
    }
  }, [])

  useEffect(() => {
    if (!routeConversationId) return
    const generation = requestGenerationRef.current
    const routeHandoff = routeHandoffRef.current
    fetchCustomerConversation(routeConversationId)
      .then((record) => {
        if (generation !== requestGenerationRef.current) return
        const resolvedMode = customerModeFor(record.customer_id)
        if (record.conversation_id !== routeConversationId || resolvedMode === null) {
          throw new Error('Customer conversation identity does not match the active route')
        }
        setMode(resolvedMode)
        setConversation(record)
        const handoffTurn =
          routeHandoff?.conversationId === record.conversation_id
          && routeHandoff.agentId === record.agent_id
          && routeHandoff.customerId === record.customer_id
            ? routeHandoff.fallbackTurn
            : null
        setTurns(record.turns.length > 0 ? record.turns : handoffTurn ? [handoffTurn] : [])
        routeHandoffRef.current = null
      })
      .catch(() => {
        if (generation !== requestGenerationRef.current) return
        routeHandoffRef.current = null
        setConversation(null)
        setTurns([])
        setMode('anonymous')
        setError(translateRef.current('customer.loadConversationError'))
      })
  }, [location.key, routeConversationId])

  useEffect(() => {
    const generation = requestGenerationRef.current
    if (routeConversationId) {
      setAgents([])
      setAgentsLoading(false)
      setAgentsError(null)
      return
    }
    setAgents([])
    setAgentsLoading(true)
    setAgentsError(null)
    fetchCustomerAgents()
      .then((response) => {
        if (generation !== requestGenerationRef.current) return
        setAgents(response.data)
      })
      .catch(() => {
        if (generation !== requestGenerationRef.current) return
        setAgentsError(translateRef.current('customer.loadAgentsError'))
      })
      .finally(() => {
        if (generation !== requestGenerationRef.current) return
        setAgentsLoading(false)
      })
  }, [location.key, routeConversationId])

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
    requestGenerationRef.current += 1
    setMode(nextMode)
    setConversation(null)
    setTurns([])
    setInput('')
    setSending(false)
    setError(null)
    navigate(agentId ? `/customer/agents/${agentId}` : '/customer', {
      replace: true,
      state: { customerMode: nextMode },
    })
  }

  const sendQuestion = async (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || sending) return
    const generation = requestGenerationRef.current
    const expectedMode = activeMode
    const expectedRouteConversationId = routeConversationId
    const expectedConversation = conversation
    const expectedAgent = selectedAgent
    setInput('')
    setError(null)
    setSending(true)

    try {
      let activeConversation: CustomerConversation
      if (expectedConversation) {
        if (
          generation !== requestGenerationRef.current
          || !expectedRouteConversationId
          || expectedConversation.conversation_id !== expectedRouteConversationId
          || expectedConversation.customer_id !== expectedMode.customerId
        ) {
          throw new CustomerBindingError(
            'Customer conversation is not bound to the active route identity',
          )
        }
        activeConversation = expectedConversation
      } else {
        if (expectedRouteConversationId || !expectedAgent) {
          throw new Error(translateRef.current('customer.noAgentError'))
        }
        const created = await createCustomerConversation(
          expectedAgent.agent_id,
          expectedMode.customerId,
        )
        if (generation !== requestGenerationRef.current) return
        if (
          !created.conversation_id
          || created.agent_id !== expectedAgent.agent_id
          || created.customer_id !== expectedMode.customerId
        ) {
          throw new CustomerBindingError(
            'Created customer conversation identity does not match the request',
          )
        }
        activeConversation = created
      }

      if (generation !== requestGenerationRef.current) return
      const response = await createCustomerRun(activeConversation.conversation_id, trimmed, {
        allowUntrustedWebSupplement,
      })
      if (generation !== requestGenerationRef.current) return
      if (response.conversation_id !== activeConversation.conversation_id) {
        throw new CustomerBindingError('Customer run response does not match its conversation')
      }
      const updated = await fetchCustomerConversation(activeConversation.conversation_id)
      if (generation !== requestGenerationRef.current) return
      const updatedMode = customerModeFor(updated.customer_id)
      if (
        updated.conversation_id !== activeConversation.conversation_id
        || updated.agent_id !== activeConversation.agent_id
        || updated.customer_id !== expectedMode.customerId
        || updatedMode === null
      ) {
        throw new CustomerBindingError(
          'Refreshed customer conversation identity does not match the run',
        )
      }
      const fallbackTurn = responseToTurn(trimmed, response)
      setMode(updatedMode)
      setConversation(updated)
      setTurns(updated.turns.length > 0 ? updated.turns : [fallbackTurn])
      if (!expectedRouteConversationId) {
        routeHandoffRef.current = {
          agentId: updated.agent_id,
          conversationId: updated.conversation_id,
          customerId: updated.customer_id,
          fallbackTurn,
        }
        navigate(`/customer/c/${updated.conversation_id}`, { replace: true })
      }
    } catch (err) {
      if (generation !== requestGenerationRef.current) return
      if (err instanceof CustomerBindingError) {
        routeHandoffRef.current = null
        setConversation(null)
        setTurns([])
        setMode('anonymous')
      }
      console.error('Customer run failed', err)
      setInput(question)
      setError(translateRef.current('customer.sendError'))
    } finally {
      if (generation === requestGenerationRef.current) {
        setSending(false)
      }
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

function customerModeFor(customerId: string | null): CustomerMode | null {
  return CUSTOMER_MODES.find((item) => item.customerId === customerId)?.id ?? null
}

function customerModeFromRouteState(state: unknown): CustomerMode | null {
  if (typeof state !== 'object' || state === null || !('customerMode' in state)) return null
  const customerMode = (state as { customerMode?: unknown }).customerMode
  return CUSTOMER_MODES.some((item) => item.id === customerMode)
    ? customerMode as CustomerMode
    : null
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
