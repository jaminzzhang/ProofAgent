import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { ChatShell } from '../../chat-core/ChatShell'
import type { ChatTurnView } from '../../chat-core/types'
import { AgentSelectionPanel } from '../../components/AgentSelectionPanel'
import { OutcomeBadge } from '../../components/OutcomeBadge'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
import { useLocale } from '../../i18n/locale'
import type {
  ConversationRecord,
  ConversationTurn,
  GovernanceDetails,
  PublishedAgentDirectoryEntry,
} from '../../api/types'
import {
  createOperatorConversation,
  createOperatorConversationRun,
  fetchOperatorAgents,
  fetchOperatorConversation,
} from './operatorAdapter'

function syntheticNewChat(agentId: string): ConversationRecord {
  return {
    conversation_id: '',
    agent_id: agentId,
    title: null,
    pinned: false,
    created_at: '',
    updated_at: '',
    turns: [],
  }
}

function hasGovernanceDetails(details?: GovernanceDetails | null): boolean {
  return (
    Boolean(details?.intent_resolution) ||
    Boolean(details?.reasoning_summary) ||
    Boolean(details?.review_results?.length) ||
    Boolean(details?.clarification_request)
  )
}

export function OperatorChatPage({ onUpdate }: { onUpdate?: () => void }) {
  const { conversationId, agentId } = useParams<{ conversationId: string; agentId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const routeConversationId = location.pathname.startsWith('/operator/c/') ? conversationId : undefined
  const isNewChat = location.pathname === '/operator/new' || Boolean(agentId)
  const [agents, setAgents] = useState<PublishedAgentDirectoryEntry[]>([])
  const [agentsLoading, setAgentsLoading] = useState(false)
  const [agentsError, setAgentsError] = useState<string | null>(null)
  const [conversation, setConversation] = useState<ConversationRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [input, setInput] = useState('')
  const [includeGovernanceDetails, setIncludeGovernanceDetails] = useState(false)
  const [allowUntrustedWebSupplement, setAllowUntrustedWebSupplement] = useState(false)
  const { t } = useLocale()

  useEffect(() => {
    if (routeConversationId) {
      setLoading(true)
      setError(null)
      setConversation(null)
      fetchOperatorConversation(routeConversationId)
        .then(setConversation)
        .catch(() => {
          setError(t('operator.loadConversationError'))
        })
        .finally(() => setLoading(false))
    } else if (isNewChat) {
      setConversation(null)
      setLoading(false)
      setError(null)
    } else {
      setLoading(false)
      setConversation(null)
    }
  }, [routeConversationId, isNewChat])

  useEffect(() => {
    if (!isNewChat) {
      setAgents([])
      setAgentsLoading(false)
      setAgentsError(null)
      return
    }
    setAgentsLoading(true)
    setAgentsError(null)
    fetchOperatorAgents()
      .then((response) => setAgents(response.data))
      .catch(() => setAgentsError(t('operator.loadAgentsError')))
      .finally(() => setAgentsLoading(false))
  }, [isNewChat])

  const selectedAgent = useMemo(() => {
    if (!isNewChat) return null
    if (agentId) return agents.find((agent) => agent.agent_id === agentId) ?? null
    return agents.length === 1 ? agents[0] : null
  }, [agentId, agents, isNewChat])

  const activeConversation = conversation ?? (
    isNewChat && selectedAgent ? syntheticNewChat(selectedAgent.agent_id) : null
  )

  const turns = useMemo(
    () => activeConversation?.turns.map(operatorTurnToView) ?? [],
    [activeConversation?.turns],
  )

  const handleSubmit = async () => {
    if (!input.trim()) return
    if (!activeConversation && !isNewChat) return
    if (isNewChat && !selectedAgent) return

    const question = input
    setInput('')
    setSending(true)

    try {
      let activeConversationId = conversation?.conversation_id
      if (isNewChat && !activeConversationId) {
        const newConversation = await createOperatorConversation(selectedAgent!.agent_id)
        activeConversationId = newConversation.conversation_id
      }

      const result = await createOperatorConversationRun(activeConversationId!, question, {
        includeGovernanceDetails,
        allowUntrustedWebSupplement,
      })
      onUpdate?.()

      if (isNewChat) {
        navigate(`/operator/c/${activeConversationId}`, { replace: true })
        return
      }

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
              question,
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
              governance_details: result.governance_details,
              links: result.links,
            },
          ],
        }
      })
    } catch (err) {
      console.error('Failed to send message', err)
      setInput(question)
      setError(t('operator.sendError'))
    } finally {
      setSending(false)
    }
  }

  if (!routeConversationId && !isNewChat) {
    return (
      <div className="flex h-[calc(100vh-160px)] flex-col px-4">
        <div className="flex flex-1 flex-col items-center justify-center space-y-4 text-center">
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">{t('operator.title')}</h1>
            <p className="mt-1 max-w-[280px] text-sm text-[var(--text-muted)]">
              {t('operator.emptyDescription')}
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

  if (isNewChat && agentsLoading) {
    return (
      <div className="py-12 flex justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (isNewChat && agentsError) {
    return (
      <AgentSelectionPanel
        title={t('operator.chooseAgentTitle')}
        description={t('operator.chooseAgentDescription')}
        agents={[]}
        emptyTitle={t('operator.unableLoadAgents')}
        emptyDescription={agentsError}
        onSelect={() => undefined}
      />
    )
  }

  if (isNewChat && !selectedAgent) {
    return (
      <AgentSelectionPanel
        title={t('operator.chooseAgentTitle')}
        description={t('operator.chooseAgentDescription')}
        agents={agentId ? [] : agents}
        unavailableAgentId={agentId}
        emptyTitle={t('operator.noAgentsTitle')}
        emptyDescription={
          agentId
            ? t('operator.unpublishedAgent')
            : t('operator.noAgentsDescription')
        }
        onSelect={(nextAgentId) => navigate(`/operator/agents/${nextAgentId}/new`)}
      />
    )
  }

  if (error && !conversation && !isNewChat) {
    return (
      <div className="flex h-[calc(100vh-160px)] flex-col px-4">
        <div className="flex flex-1 flex-col items-center justify-center space-y-4 text-center">
          <div>
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">{t('operator.loadErrorTitle')}</h1>
            <p className="mt-1 max-w-[320px] text-sm text-[var(--text-muted)]">{error}</p>
          </div>
          <button
            onClick={() => {
              if (!routeConversationId) return
              setError(null)
              setLoading(true)
              fetchOperatorConversation(routeConversationId)
                .then(setConversation)
                .catch(() => {
                  setError(t('operator.loadConversationError'))
                })
                .finally(() => setLoading(false))
            }}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            {t('operator.retry', 'Retry')}
          </button>
        </div>
      </div>
    )
  }

  if (!activeConversation) {
    return null
  }

  return (
    <ChatShell
      title={t('operator.title')}
      subtitle={selectedAgent?.display_name ?? t('operator.defaultSubtitle')}
      turns={turns}
      inputValue={input}
      onInputChange={setInput}
      onSubmit={handleSubmit}
      sending={sending}
      untrustedWebSupplementToggle={{
        checked: allowUntrustedWebSupplement,
        onChange: setAllowUntrustedWebSupplement,
      }}
      placeholder={t('operator.placeholder')}
      submitLabel={t('operator.submit')}
      emptyTitle={t('operator.emptyTitle')}
      emptyDescription={t('operator.chatEmptyDescription')}
      error={error}
      footer={
        <label className="inline-flex items-center gap-2 text-xs font-medium text-[var(--text-muted)]">
          <input
            type="checkbox"
            checked={includeGovernanceDetails}
            onChange={(event) => setIncludeGovernanceDetails(event.target.checked)}
            disabled={sending || loading}
            className="h-4 w-4 rounded border-[var(--border)] text-[var(--accent)] focus:ring-[var(--accent)]"
          />
          {t('operator.showGovernanceDetails')}
        </label>
      }
      renderAssistantMeta={(turn) => {
        const operatorTurn = findOperatorTurn(activeConversation, turn.id)
        if (!operatorTurn) return null
        return <OperatorMessageMeta turn={operatorTurn} />
      }}
      renderAssistantActions={(turn) => {
        const operatorTurn = findOperatorTurn(activeConversation, turn.id)
        if (!operatorTurn) return null
        return <OperatorGovernanceDetails turn={operatorTurn} />
      }}
      sendingLabel={
        <div className="flex items-center gap-3">
          <div className="flex gap-1">
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--text-muted)]" />
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--text-muted)] [animation-delay:150ms]" />
            <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--text-muted)] [animation-delay:300ms]" />
          </div>
          <span className="text-xs font-medium text-[var(--text-muted)]">{t('operator.executing')}</span>
        </div>
      }
    />
  )
}

function operatorTurnToView(turn: ConversationTurn): ChatTurnView {
  return {
    id: turn.turn_id,
    question: turn.question,
    createdAt: turn.created_at,
    assistant: {
      content: turn.final_output,
    },
  }
}

function findOperatorTurn(conversation: ConversationRecord, turnId: string): ConversationTurn | undefined {
  return conversation.turns.find((turn) => turn.turn_id === turnId)
}

function OperatorMessageMeta({ turn }: { turn: ConversationTurn }) {
  const { t, formatNumber } = useLocale()

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] pb-3">
      <OutcomeBadge outcome={turn.outcome} />
      {turn.evidence.length > 0 && (
        <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
          {formatNumber(turn.evidence.length)} {t('operator.evidence')} {turn.evidence.length === 1 ? t('operator.source') : t('operator.sources')}
        </span>
      )}
      <div className="ml-auto flex gap-3">
        <a
          href={`http://localhost:5173/runs/${turn.run_id}`}
          target="_blank"
          rel="noreferrer"
          className="text-[11px] font-bold uppercase tracking-tight text-[var(--accent)] hover:underline"
        >
          {t('operator.auditTrace')}
        </a>
        <a
          href={turn.links.receipt}
          target="_blank"
          rel="noreferrer"
          className="text-[11px] font-bold uppercase tracking-tight text-[var(--accent)] hover:underline"
        >
          {t('operator.receipt')}
        </a>
      </div>
    </div>
  )
}

function OperatorGovernanceDetails({ turn }: { turn: ConversationTurn }) {
  const { t } = useLocale()

  return (
    <>
      {turn.outcome === 'WAITING_FOR_APPROVAL' && (
        <div className="flex gap-2 pt-1">
          <a
            href={`http://localhost:5173/runs/${turn.run_id}#approval`}
            target="_blank"
            rel="noreferrer"
            className="inline-block rounded-md bg-blue-600 px-4 py-1.5 text-[11px] font-bold uppercase tracking-wider text-white transition-colors hover:bg-blue-700"
          >
            {t('operator.reviewApproval')}
          </a>
        </div>
      )}

      {hasGovernanceDetails(turn.governance_details) && (
        <details className="border-t border-[var(--border)] pt-2">
          <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            {t('operator.governanceSummary')}
          </summary>
          <pre className="mt-3 max-h-56 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--bg-base)] p-3 font-mono text-[11px] leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap">
            {JSON.stringify(turn.governance_details, null, 2)}
          </pre>
        </details>
      )}
    </>
  )
}
