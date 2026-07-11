import {
  createConversation,
  createConversationRun,
  deleteConversation,
  fetchChatAgents,
  fetchConversation,
  fetchConversations,
  updateConversation,
} from '../../api/client'
import type {
  ChatRunResponse,
  ConversationRecord,
  ConversationTurn,
  PublishedAgentDirectoryResponse,
} from '../../api/types'

export const fetchOperatorAgents = fetchChatAgents
export const fetchOperatorConversations = fetchConversations
export const createOperatorConversation = createConversation
export const updateOperatorConversation = updateConversation
export const deleteOperatorConversation = deleteConversation

export interface OperatorEvidenceView {
  source: string
  citation: string | null
  status: string | null
  scores: unknown
}

export type OperatorConversationTurn = Omit<ConversationTurn, 'evidence'> & {
  evidence: OperatorEvidenceView[]
}

export type OperatorConversationRecord = Omit<ConversationRecord, 'turns'> & {
  turns: OperatorConversationTurn[]
}

export type OperatorChatRunResponse = Omit<ChatRunResponse, 'evidence'> & {
  evidence: OperatorEvidenceView[]
}

export async function fetchOperatorConversation(
  conversationId: string,
): Promise<OperatorConversationRecord> {
  const conversation = await fetchConversation(conversationId)
  return {
    ...conversation,
    turns: conversation.turns.map((turn) => ({
      ...turn,
      evidence: normalizeOperatorEvidence(turn.evidence),
    })),
  }
}

interface OperatorRunOptions {
  includeGovernanceDetails?: boolean
  allowUntrustedWebSupplement?: boolean
}

export function createOperatorConversationRun(
  conversationId: string,
  question: string,
  options: OperatorRunOptions = {},
): Promise<OperatorChatRunResponse> {
  return createConversationRun(
    conversationId,
    question,
    {
      includeGovernanceDetails: options.includeGovernanceDetails ?? false,
      allowUntrustedWebSupplement: options.allowUntrustedWebSupplement ?? false,
    },
  ).then((result) => ({
    ...result,
    evidence: normalizeOperatorEvidence(result.evidence),
  }))
}

function normalizeOperatorEvidence(evidence: unknown): OperatorEvidenceView[] {
  if (!Array.isArray(evidence)) return []

  return evidence.map((item, index) => {
    const record = isRecord(item) ? item : null
    const citation = nonBlankString(record?.citation)
    const source = nonBlankString(record?.source) ?? nonBlankString(item) ?? citation

    return {
      source: source ?? `Source ${index + 1}`,
      citation,
      status: nonBlankString(record?.status),
      scores: record?.scores ?? record?.score ?? record?.admission_score ?? null,
    }
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nonBlankString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized || null
}

export type { ChatRunResponse, ConversationRecord, PublishedAgentDirectoryResponse }
