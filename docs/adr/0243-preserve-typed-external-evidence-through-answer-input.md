# ADR-0243: Preserve typed external evidence through answer input

## Status

[FRAME | HIGH] Accepted for the user-authorized P0-3 slice on 2026-09-06. Builds on ADR-0241 and ADR-0242.

## Decision

Introduce a bounded provider-neutral structured record on Candidate and Evidence. Decimal values remain strings, integers never pass through floating point, and null remains distinct from absent fields. A record cannot grant itself admission or override its provider-derived source identity.

Dify supplies segment text. An explicit frozen binding `content_format: structured_json` declares that each selected segment contains a complete `proofagent-structured-evidence.v1` JSON record. This is an application content convention, not a claim about Dify-native typed retrieval. Malformed, ambiguous or mixed Q&A structured content fails closed. Default text retrieval remains unchanged.

The Control Plane validates content identity and structure, performs existing admission, then renders each accepted record with its own exact source/citation in both initial and repair answer requests. No provider metadata, model output, conversation or plain text is promoted into typed facts automatically. Observation Truth binds and preserves the record together with its original content.

This slice proves type/value/provenance transport, not semantic correctness, independent numeric verification or production readiness. P0-4 remains responsible for answer validation; production external-provider publication remains separately gated.
