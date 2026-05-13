# Controlled Conversation Context For Assisted Chat

The Assisted QA Chat Frontend will support automatic multi-turn context injection, but conversation history must enter each Harness run as Controlled Conversation Context rather than raw transcript injection. We chose this because staff-facing chat needs natural follow-up behavior, while Proof Agent must preserve per-turn retrieval, evidence admission, policy enforcement, validation, trace, and Governance Receipt semantics.

Each chat turn remains a governed Harness run with its own evidence evaluation and receipt. The Conversation Store records the operator-facing timeline and links turns to RunStore artifacts, while RunStore remains the source of run traces, receipts, and metadata. The context admission step should redact sensitive content, enforce length and relevance limits, record a trace-safe admission summary, and never allow prior answers or raw conversation text to replace evidence retrieval for the current question.
