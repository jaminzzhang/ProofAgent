---
status: accepted
---

# Use one review draft over an immutable parser baseline

[FRAME | HIGH] One immutable Insurance Rule Metadata Parser Proposal initializes one Current Insurance Rule Metadata Review Draft for each current default or override review. Dashboard edits and Metadata Workbook Import update that same audited draft; a human value differing from the parser is a visible, reasoned change awaiting approval, not a blocking conflict. Only divergent server and workbook edits to the same exact export-base field create a Metadata Review Draft Conflict. Missing parser values produce `needs_input`, and approval binds the complete draft, differences, reasons, and review identity. This partially supersedes ADR-0136's parallel PDF/workbook proposal model while preserving its mandatory human-authority boundary.
