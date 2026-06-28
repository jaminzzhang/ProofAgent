# run_4840c6ed Controlled ReAct Intent Analysis

## Scope

- [KNOWN] Confidence: HIGH. This note analyzes local run `run_4840c6ed`.
- [KNOWN] Confidence: HIGH. Run artifacts live at `runs/history/run_4840c6ed/trace.jsonl`, `runs/history/run_4840c6ed/governance_receipt.md`, and `runs/history/run_4840c6ed/run_meta.json`.
- [KNOWN] Confidence: HIGH. The run belongs to Agent `agent_management_insurance_specialist`.
- [KNOWN] Confidence: HIGH. The run question is `平安御享的主要保险产品条款有哪些？`.
- [KNOWN] Confidence: HIGH. The final outcome is `ANSWERED_WITH_CITATIONS`.
- [KNOWN] Confidence: HIGH. The validation capture is `runs/config/validation_captures/vcap_df3dcbc8a8e3/capture.json`.

## Controlled ReAct Shape

- [KNOWN] Confidence: HIGH. The run uses `runtime: controlled_react_orchestrator`, `workflow.template: react_enterprise_qa_v3`, and descriptor version `react_enterprise_qa.v3`.
- [KNOWN] Confidence: HIGH. V3 Control ReAct prepares pre-loop state in `ControlledReActOrchestrator._prepare_pre_loop_state()`, where the optional Intent Resolution port runs before planning.
- [KNOWN] Confidence: HIGH. V3 stage results are projected after the Orchestrator returns by `emit_controlled_react_trace_projection()` in Delivery.
- [COMPUTED] Confidence: HIGH. In this trace, runtime events appear first, and stage-result projection events start at sequence 21.
- [INFERRED] Confidence: HIGH. The chronological trace can make V3 look like retrieval happened before Intent Resolution, but the later stage result is a projection of Orchestrator state rather than proof of event order.

## Intent Resolution Evidence

- [COMPUTED] Confidence: HIGH. The trace contains a `workflow_stage_result` for `stage_id: intent_resolution` at sequence 21.
- [COMPUTED] Confidence: HIGH. That stage summary is `resolution_id=intent_1`, `domain_intent=public_insurance_knowledge_query`, `recommended_next_action=plan_retrieval`, and `confidence=0.85`.
- [COMPUTED] Confidence: HIGH. The validation capture has the same `intent_resolution` stage result and includes `intent_resolution` in `fact_refs`.
- [COMPUTED] Confidence: HIGH. The ordinary trace does not contain an `event_type: intent_resolution` event.
- [COMPUTED] Confidence: HIGH. The ordinary trace does not contain an `event_type: retrieval_query_set` event.
- [COMPUTED] Confidence: HIGH. The ordinary trace does not contain a `model_request` or `model_response` with `role: intent_resolution`.
- [COMPUTED] Confidence: HIGH. The validation capture includes only one LLM interaction, and it is for `stage_id: model_answer`, `role: final_answer`.
- [COMPUTED] Confidence: HIGH. The Governance Receipt has no `Intent Resolution` section, because receipt generation reads `intent_resolution` trace events and this run has none.

## Interpretation

- [INFERRED] Confidence: MED. Intent recognition probably happened, because the run state carries a non-default-looking intent summary for `public_insurance_knowledge_query`.
- [KNOWN] Confidence: HIGH. The run does not preserve audit-grade evidence of the Intent Resolution model call in trace or validation capture.
- [KNOWN] Confidence: HIGH. The run does not preserve the full Intent Resolution Contract in trace, including `user_goal`, `known_facts`, `missing_fields`, `ambiguities`, `risk_flags`, or `retrieval_query_set`.
- [INFERRED] Confidence: HIGH. For operator diagnosis, this is an observability gap: the run has a stage projection but lacks the audit events and validation interaction needed to verify how the intent was produced.

## Query Rewrite Evidence

- [COMPUTED] Confidence: HIGH. The retrieval plan event has `retrieval_query_count: 0`.
- [COMPUTED] Confidence: HIGH. The retrieval plan uses `strategy: agentic`, `provider: local_index`, and `max_queries: 3`.
- [COMPUTED] Confidence: HIGH. The retrieval path emits `fallback_reason: planner or evaluator model not configured` and `fallback_strategy: single_step`.
- [COMPUTED] Confidence: HIGH. The actual retrieval step uses the original question as its query: `平安御享的主要保险产品条款有哪些？`.
- [KNOWN] Confidence: HIGH. `_InvocationKnowledgeObservationAdapter.observe()` builds `KnowledgeRetrievalRequest` without passing `state.intent_resolution.retrieval_query_set`.
- [KNOWN] Confidence: HIGH. The older ReAct stage behavior path passes `_retrieval_query_set_from_state(state)` into `KnowledgeRetrievalRequest`.
- [INFERRED] Confidence: HIGH. V3 currently drops Intent Resolution query expansion before retrieval, so this run shows no query rewrite or query-set execution even though the Agent config has `retrieval.max_queries: 3`.
- [KNOWN] Confidence: HIGH. `_context_summary()` for the first planning round returns only `observation_count=0`, so the V3 planner context also does not expose the intent summary or retrieval query set.

## Retrieval Outcome

- [COMPUTED] Confidence: HIGH. Local Index routing selected two documents from four candidates.
- [COMPUTED] Confidence: HIGH. The accepted evidence count is five.
- [COMPUTED] Confidence: HIGH. All five accepted evidence chunks cite `doc_5750121a` / `rev_5750121a`.
- [INFERRED] Confidence: MED. The final answer is plausibly grounded in the selected product-clause document, but the trace does not prove that a query expansion path improved recall.

## Recommended Query Set

Use a bounded Retrieval Query Set of three required items for this user question:

1. [INFERRED] Confidence: HIGH. `平安御享一生终身寿险（分红型） 保险条款 保险责任 责任免除`
   - Intent angle: original wording plus canonical product alias.
   - Reason: binds `平安御享` to the likely full product name and targets core clauses.
2. [INFERRED] Confidence: HIGH. `平安御享 2130 产品条款 现金价值 保单贷款 红利分配 犹豫期`
   - Intent angle: entity and clause qualifiers.
   - Reason: adds product code and high-value clause topics likely to appear in the policy document.
3. [INFERRED] Confidence: HIGH. `平安御享 主险 保障责任 保险期间 缴费 宽限期 退保`
   - Intent angle: insurance business terminology and synonyms.
   - Reason: broadens from "主要条款" to concrete insurance-policy section names.

## Product Fix Recommendations

1. [KNOWN] Confidence: HIGH. Emit V3 `intent_resolution` and `retrieval_query_set` trace events after `_prepare_pre_loop_state()` resolves intent.
2. [KNOWN] Confidence: HIGH. Add V3 validation capture support for the Intent Resolution LLM request and response, matching the validation-only capture pattern used for `model_answer`.
3. [KNOWN] Confidence: HIGH. Pass `state.intent_resolution.retrieval_query_set` into `KnowledgeRetrievalRequest` in `_InvocationKnowledgeObservationAdapter.observe()`.
4. [INFERRED] Confidence: HIGH. Add the intent summary and selected Retrieval Query Set to the V3 planner context, or synthesize a governed `plan_retrieval` proposal from high-confidence retrieval-ready intent under an explicit Control Plane rule.
5. [KNOWN] Confidence: HIGH. Add tests proving V3 emits `intent_resolution` and `retrieval_query_set` events.
6. [KNOWN] Confidence: HIGH. Add tests proving V3 retrieval uses Intent Resolution query items and records `retrieval_query_count > 0` when those items exist.
7. [KNOWN] Confidence: HIGH. Add tests proving the Governance Receipt renders Intent Resolution for V3 runs.
8. [INFERRED] Confidence: MED. Add document routing metadata for product name, product alias, product code, document type, and business line so Local Index can narrow `平安御享` product-clause documents more deterministically.

## Bottom Line

- [INFERRED] Confidence: MED. `run_4840c6ed` likely did classify the user intent as a public insurance knowledge query.
- [KNOWN] Confidence: HIGH. `run_4840c6ed` did not leave complete audit evidence for that classification.
- [KNOWN] Confidence: HIGH. `run_4840c6ed` did not use Intent Resolution for query rewrite or query-set retrieval.
- [INFERRED] Confidence: HIGH. The highest-leverage fix is not prompt tuning; it is V3 orchestration wiring and observability: trace Intent Resolution, capture the interaction for validation, and propagate `retrieval_query_set` into retrieval.
