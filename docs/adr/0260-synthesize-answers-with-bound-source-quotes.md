# ADR-0260: Synthesize answers with bound source quotes

Date: 2026-09-13

Update 2026-09-14: ADR-0262 supersedes the exact claim-substring requirement below;
semantic claim labels are bound to answer conclusions through grounding review.

## Decision

[FRAME | HIGH] The user explicitly authorizes evidence-grounded LLM summaries and
analysis, including paraphrases, combinations and table interpretation, with original
quoted evidence in the delivered answer. This supersedes the ordinary text answer's
verbatim-only restriction and automatic source-ID repair in ADR-0244/0257/0259.
Evidence admission, authorization, cumulative budgets and fail-closed errors remain.

The generation contract retains `message` and `citations`, and requires `quotes`
(`claim`, `text`, `citation`) plus `coverage` (each user requirement ID and an
`answered`, `needs_evidence` or `needs_user_input` disposition). Quotes must bind to
the exact admitted source and to a substring of the answer; only whitespace may be
normalized in source matching. Tables and conditional paragraphs can be quoted intact.
Original text is displayed in numbered literal blocks, separate from generated prose.

Control first validates quote bindings, IDs, bounds and safety, then makes a separate
bounded LLM review request covering claim support, event-time/condition preservation,
and whether every user requirement is actually addressed or explicitly left open.
The review is a separate call to the same answer provider/model, not an independent
model ensemble; errors can be correlated. It runs through the same policy and budget path. Malformed,
negative, unavailable or policy-denied reviews cannot authorize delivery. Repair keeps
analysis, quotes and requirements; it no longer forces source-ID selection.

The existing source-bound `message`/`citations` form remains supported for literal
facts and deterministic/typed adapters under its existing strict validators; absence
of quotes never enables unconstrained synthesis. New quoted answers require a separate
review before runtime admission. Historical selection helpers remain for offline
reproduction, not as the runtime default or recovery strategy.

Model review is fallible assessment, not deterministic semantic proof or source
authenticity/freshness verification. A quote-binding pass alone cannot satisfy Task
acceptance. Required unknown semantic criteria and strict assurance remain fail closed;
no model confidence, coverage self-report or review result grants tool authority.

## Verification

Synthetic contract and orchestration tests cover valid paraphrase/table quotes,
forged quotes, wrong sources, lost conditions, missing user requirements, repair,
review policy/budget failures and visible original text. Run `run_6ed2bd2f` supplies
the regression motivation, not an independent quality benchmark. Real model replay
and deployment are separate evidence.
