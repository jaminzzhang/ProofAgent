import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { ChatShell } from '../../chat-core/ChatShell'
import type { ChatTurnView } from '../../chat-core/types'
import { AgentSelectionPanel } from '../../components/AgentSelectionPanel'
import { OutcomeBadge } from '../../components/OutcomeBadge'
import { LoadingSpinner } from '../../components/ui/LoadingSpinner'
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

  useEffect(() => {
    if (routeConversationId) {
      setLoading(true)
      setError(null)
      setConversation(null)
      fetchOperatorConversation(routeConversationId)
        .then(setConversation)
        .catch(() => {
          setError('Failed to load conversation. It may have been deleted or the server is unavailable.')
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
      .catch(() => setAgentsError('Failed to load Published Agents.'))
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
      setError('Failed to send message. Please try again.')
    } finally {
      setSending(false)
    }
  }

  if (!routeConversationId && !isNewChat) {
    return (
      <div className="flex h-[calc(100vh-160px)] flex-col px-4">
        <div className="flex flex-1 flex-col items-center justify-center space-y-4 text-center">
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">Operator Chat</h1>
            <p className="mt-1 max-w-[280px] text-sm text-[var(--text-muted)]">
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
        title="Choose a Published Agent"
        description="Select a Published Agent before starting operator chat."
        agents={[]}
        emptyTitle="Unable to load Published Agents"
        emptyDescription={agentsError}
        onSelect={() => undefined}
      />
    )
  }

  if (isNewChat && !selectedAgent) {
    return (
      <AgentSelectionPanel
        title="Choose a Published Agent"
        description="Select a Published Agent before starting operator chat."
        agents={agentId ? [] : agents}
        unavailableAgentId={agentId}
        emptyTitle="No Published Agents are available"
        emptyDescription={
          agentId
            ? 'This Agent is not published for operator chat. Publish it before opening chat.'
            : 'Import an Agent template, validate it, and publish it in the Dashboard first.'
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
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">Unable to Load Conversation</h1>
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
                  setError('Failed to load conversation. It may have been deleted or the server is unavailable.')
                })
                .finally(() => setLoading(false))
            }}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition hover:opacity-90"
          >
            Retry
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
      title="Operator Chat"
      subtitle={selectedAgent?.display_name ?? 'Operator-facing governed question answering.'}
      turns={turns}
      inputValue={input}
      onInputChange={setInput}
      onSubmit={handleSubmit}
      sending={sending}
      untrustedWebSupplementToggle={{
        checked: allowUntrustedWebSupplement,
        onChange: setAllowUntrustedWebSupplement,
      }}
      placeholder="Type your question for the assistant"
      submitLabel="Ask"
      emptyTitle="Start a Conversation"
      emptyDescription="Ask the Insurance Service QA agent anything about policies or processes."
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
          Show governance details
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
          <span className="text-xs font-medium text-[var(--text-muted)]">Harness executing...</span>
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
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] pb-3">
      <OutcomeBadge outcome={turn.outcome} />
      {turn.evidence.length > 0 && (
        <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
          {turn.evidence.length} Evidence {turn.evidence.length === 1 ? 'Source' : 'Sources'}
        </span>
      )}
      <div className="ml-auto flex gap-3">
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
  )
}

function OperatorGovernanceDetails({ turn }: { turn: ConversationTurn }) {
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
            Review Approval Request
          </a>
        </div>
      )}

      {hasGovernanceDetails(turn.governance_details) && (
        <details className="border-t border-[var(--border)] pt-2">
          <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            ReAct Governance
          </summary>
          <pre className="mt-3 max-h-56 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--bg-base)] p-3 font-mono text-[11px] leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap">
            {JSON.stringify(turn.governance_details, null, 2)}
          </pre>
        </details>
      )}
    </>
  )
}
