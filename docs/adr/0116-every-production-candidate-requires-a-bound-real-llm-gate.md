# Every Production Candidate Requires a Bound Real-LLM Gate

Accepted.

[FRAME | HIGH] ADR-0033's real-LLM regression requirement is a hard gate for every formal production candidate, not only an optional diagnostic for loop changes. The gate runs the immutable candidate image with its exact candidate Agent versions and production-equivalent model configuration against every in-scope first-release Agent, covering intent resolution, retrieval and evidence, tool permission and denial, governed refusal, and loop-budget termination. Deterministic gates must also pass.

[FRAME | HIGH] A skipped run, missing provider credential, stale result, incomplete Agent coverage, threshold failure, or result that cannot be bound to the candidate image and configuration blocks release. The real-LLM result and its bounded cost and latency evidence become release artifacts; passing a source-tree or deterministic-only test run cannot substitute for the candidate-bound gate.
