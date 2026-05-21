export interface ChatAssistantView {
  content: string
  progressState?: string
  sources?: Array<string | { source_id: string; label: string; excerpt?: string | null }>
  suggestedNextSteps?: string[]
}

export interface ChatTurnView {
  id: string
  question: string
  createdAt: string
  assistant: ChatAssistantView
}
