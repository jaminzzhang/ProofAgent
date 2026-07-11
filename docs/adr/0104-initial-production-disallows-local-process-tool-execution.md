# Initial Production Disallows Local Process Tool Execution

Accepted.

[FRAME | HIGH] The initial formal release rejects MCP stdio and Local Tool Handler execution in production before discovery, validation, publication, or runtime invocation; those paths remain available only for deterministic local demos and tests. This narrows the production applicability of ADR-0034 without removing the repository's local protocol fixtures. Sandboxed script or command execution is a separate post-release capability that requires its own isolation design, threat model, acceptance gates, and architectural decision before production use.
