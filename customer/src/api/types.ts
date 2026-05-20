export type CustomerRunProgressState =
  | 'authenticating'
  | 'retrieving_evidence'
  | 'checking_account_data'
  | 'validating_answer'
  | 'preparing_response'
  | 'completed'

export interface CustomerConversation {
  conversation_id: string
  agent_id: string
  customer_id: string | null
  turns: CustomerTurn[]
}

export interface CustomerTurn {
  turn_id: string
  run_id: string
  question: string
  response_snapshot: CustomerRunResponse
  created_at: string
}

export interface CustomerRunResponse {
  conversation_id: string
  turn_id: string
  run_id: string
  progress_state: CustomerRunProgressState
  message: string
  safe_sources: string[]
  handoff_safe_message?: string | null
  suggested_next_steps?: string[]
}

export interface CustomerFeedbackResponse {
  conversation_id: string
  turn_id: string
  feedback: {
    rating: 'up' | 'down'
    comment: string | null
    applies_to_training: false
  }
}
