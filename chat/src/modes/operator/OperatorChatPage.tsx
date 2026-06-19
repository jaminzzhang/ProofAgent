import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowUpRight, ExternalLink } from 'lucide-react'
import { Badge, Button, Card } from '@proofagent/ui'

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

/** Dashboard base URL for run/approval deep-links (env-configurable). */
const DASHBOARD_URL = import.meta.env.VITE_DASHBOARD_URL ?? 'http://localhost:5173'

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
      <div className="flex h-full flex-col px-4">
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
      <div className="flex h-full flex-col px-4">
        <div className="flex flex-1 flex-col items-center justify-center space-y-4 text-center">
          <div>
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">{t('operator.loadErrorTitle')}</h1>
            <p className="mt-1 max-w-[320px] text-sm text-[var(--text-muted)]">{error}</p>
          </div>
          <Button
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
          >
            {t('operator.retry', 'Retry')}
          </Button>
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
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] pb-3">
      <OutcomeBadge outcome={turn.outcome} />
      {turn.evidence.length > 0 && (
        <Badge variant="subtle">
          {formatNumber(turn.evidence.length)}{' '}
          {turn.evidence.length === 1 ? t('operator.source') : t('operator.sources')}
        </Badge>
      )}
      <div className="ml-auto flex items-center gap-1">
        <a
          href={`${DASHBOARD_URL}/runs/${turn.run_id}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)]"
        >
          {t('operator.auditTrace')}
          <ExternalLink size={11} />
        </a>
        <span className="text-[var(--border-strong)]">·</span>
        <a
          href={turn.links.receipt}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-0.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)]"
        >
          {t('operator.receipt')}
          <ExternalLink size={11} />
        </a>
      </div>
    </div>
  )
}

function OperatorGovernanceDetails({ turn }: { turn: ConversationTurn }) {
  const { t } = useLocale()

  return (
    <div className="space-y-3 pt-1">
      {/* Inline evidence/citation chips with excerpts */}
      {turn.evidence.length > 0 && (
        <div className="space-y-1.5">
          {turn.evidence.map((ev, idx) => {
            const sourceId = typeof ev === 'string' ? ev : ev.source_id
            const label = typeof ev === 'string' ? ev : ev.label ?? ev.source_id
            const excerpt = typeof ev === 'string' ? null : ev.excerpt
            return (
              <div
                key={`${sourceId}-${idx}`}
                title={excerpt ?? undefined}
                className="flex items-start gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2.5 py-1.5"
              >
                <span className="mt-0.5 font-mono text-[10px] text-[var(--text-muted)]">
                  [{idx + 1}]
                </span>
                <div className="min-w-0">
                  <span className="block truncate text-xs font-medium text-[var(--text-primary)]">
                    {label}
                  </span>
                  {excerpt && (
                    <span className="line-clamp-1 text-[11px] text-[var(--text-muted)]">
                      {excerpt}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Inline approval action — links to Dashboard approval console */}
      {turn.outcome === 'WAITING_FOR_APPROVAL' && (
        <Card className="flex items-center justify-between gap-3 border-[var(--warning-border)] bg-[var(--warning-bg)] p-3">
          <span className="text-xs font-medium text-[var(--warning-fg)]">
            {t('operator.reviewApproval')}
          </span>
          <Button
            variant="outline"
            size="sm"
            asChild
          >
            <a
              href={`${DASHBOARD_URL}/runs/${turn.run_id}#approval`}
              target="_blank"
              rel="noreferrer"
            >
              {t('operator.reviewApproval')}
              <ArrowUpRight size={13} />
            </a>
          </Button>
        </Card>
      )}

      {/* Structured governance disclosure */}
      {hasGovernanceDetails(turn.governance_details) && (
        <details className="rounded-md border border-[var(--border)] bg-[var(--bg-base)]">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            {t('operator.governanceSummary')}
          </summary>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap border-t border-[var(--border)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--text-secondary)]">
            {JSON.stringify(turn.governance_details, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}
