# Unified Chat Frontend With Separated Projections

Proof Agent will consolidate the operator-facing Assisted QA Chat Frontend and customer-facing Customer Service Chat Frontend into one `chat/` SPA with shared design, routing conventions, and conversation flow. We chose this because a single chat shell reduces duplicated frontend code and keeps the product experience coherent, while mode-specific adapters preserve the existing trust boundary between `/api/chat/...` internal run projections and `/api/customer/...` Customer-Safe Response Projection values.

The unified SPA uses route namespaces such as `/operator` and `/customer` to select audience mode. Customer mode must not expose audit links, Governance Detail Projection, approval state, raw run identifiers, receipt links, or internal handoff status, and the independent `customer/` Vite app is treated as a migration source rather than a long-term surface.

The migration does not preserve the old un-namespaced chat routes (`/`, `/new`, or `/c/:conversationId`) as compatibility redirects. Operators use the explicit `/operator` namespace, and customers use the explicit `/customer` namespace.

The root route is a minimal mode selection entry for the unified SPA, not a Dashboard, marketing page, or legacy Assisted Chat redirect. It should expose only clear Operator Chat and Customer Chat entry points plus lightweight service status.
