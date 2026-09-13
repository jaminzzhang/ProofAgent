# run_1fbcbc32 correction evidence

Date: 2026-09-12. User authorization: “按你的建议修正优化。”
Plan: `docs/research/run-1fbcbc32-diagnosis-2026-09-12.md`.
Decision: ADR-0257. Existing unrelated working-tree edits are preserved.

## Acceptance and verification

| Acceptance | Evidence |
|---|---|
| CJK spaces do not invent numerical conflicts; altered signs/units/digits still fail | `tests/test_performance_answer_contract.py` and existing answer-fact adversarial tests |
| Table weaknesses retain subject/period/comparison/units/notes | Synthetic table positive and tampering tests |
| No-year overview cannot silently introduce 2025 | Clarification policy regression |
| Analysis selects first; compact input; duplicate evidence removed | Real FinalAnswerAttemptRunner with a synthetic boundary provider |
| Strengths-only answer fails even when topic words match | Adequacy regression, including lower cost not being a negative result |
| One selection repair cannot drop the two-sided contract | Runner regression with persistent omission |
| Required queries do not preclude bounded gap retrieval | Orchestrator test through bound Observation Truth |
| Retrieval budget remains binding when coverage is missing | Orchestrator budget regression |
| Both failed attempts remain diagnosable | Existing diagnostic list, latest first |
| Different applicability/conflict metadata survives deduplication | Answer assurance regression |
| Over-limit selection reports safe actual count and limit without truncation | 30-item selection fails after one repair, preserving both diagnostics |
| The composed Agentset path uses these controls | Synthetic HTTP and model boundaries exercise intent, admission, planning, selection and final validation |

## Observed RED

- Initial `tests/test_performance_answer_contract.py`: 6 failed, 4 passed.
  Failed behaviors: presentation false negative, absent table fact, missing two-sided
  adequacy, invented year, late selection, repair omission admitted.
- Added retrieval cases: 2 failed, 56 passed in retrieval task completion suite.
  Premature finalization and missing coverage bypassed the budget boundary.
- Both-failure diagnostic regression failed (one diagnostic retained instead of two).
- These were application assertion failures, not environment or import errors.

## Local captured-evidence experiment

[KNOWN | HIGH] The original six accepted evidence entries were read from the existing
sensitive validation capture, without copying the capture into tests. The current
FinalAnswerAttemptRunner was exercised using a deterministic source-option chooser.
It selected eight relevant statements from 76 options, with four unique evidence
chunks and 8,730 request characters. One offline answer invocation returned
ANSWERED_WITH_CITATIONS, retaining table values 23.5 / 28.3 / decline 4.8 and the fixed
latestness/full-coverage limitation. No network or live model call was performed.

This experiment checks the current projection, selection, rendering and admission
path, not the ability of DeepSeek to select compliant IDs on a future call. It does
not independently establish that the captured financial document is authentic or
the latest available report. Historical statement IDs are not reused.

## Review and remaining verification

Review is self-review, not an independent agent audit. This work does not include
production deployment, source-provider publication, model credentials, or external
diagnostic replay. Real-model stability remains unverified and requires explicit
consent to send diagnostic inputs externally. The bounded profile deliberately
does not claim comprehensive company research or general semantic entailment.

[KNOWN | HIGH] Final local checks on 2026-09-12:

- `.venv/bin/python -m pytest tests/ -q`: **2998 passed, 102 skipped,
  2 deselected**, 43.85 seconds. Executed with loopback permission for local HTTP
  tests. Two existing warnings concern Authlib deprecation and FrozenDict serialization.
- Focused answer/assurance regression suite: **133 passed**.
- `.venv/bin/python -m ruff check proof_agent tests docs/research/run-1fbcbc32-offline-probe.py`: passed.
- `.venv/bin/python -m mypy proof_agent`: passed, 419 source files.
- `python3 scripts/check-domain-contexts.py` and `git diff --check`: passed.
- Current captured-evidence probe: one deterministic answer call, eight selected
  statements, four unique evidence chunks, `ANSWERED_WITH_CITATIONS`, no diagnostics.

Status: **LOCAL_VERIFIED** for the bounded implementation and offline acceptance;
**PARTIAL_VERIFICATION** for end-to-end operational readiness. No real-model replay,
service restart, deployment or browser verification was performed. This task changed
backend behavior and documentation, not frontend code. The full test run includes
pre-existing workspace changes; it is not evidence that those changes belong to this
fix. No commit or push was made.
