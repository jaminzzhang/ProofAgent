# run_f2cc8fc0 Workflow Analysis

## Scope

This note analyzes `run_f2cc8fc0` from the local run history:

- History directory: `/Users/jamin/Dev/mz-projects/ProofAgent/runs/history/run_f2cc8fc0`
- Agent: `institution_insurance_specialist`
- Published version: `version_ccacbac5`
- Workflow Template: `react_enterprise_qa_v2`
- Descriptor version: `react_enterprise_qa.v2`
- Question: `介绍平安御享的主要优缺点`
- Outcome: `ANSWERED_WITH_CITATIONS`

The analysis distinguishes four different things that can look like "nodes":

- Workflow Template Stages: governed Control Envelope stages visible to Agent owners.
- Runtime graph nodes: LangGraph scheduling mechanics.
- Trace events: audit facts emitted during execution.
- Knowledge index nodes: LlamaIndex document chunks referenced in citations as `#node=...`.

## Stage Descriptor Versus Runtime Path

`react_enterprise_qa_v2` exposes ten Workflow Template Stages:

| Stage | Purpose | run_f2cc8fc0 status |
| --- | --- | --- |
| `intent_resolution` | Classify the user goal and recommend a governed next action. | Executed; resolved `public_insurance_knowledge_query` with confidence `0.95`. |
| `plan` | Produce a governed ReAct action proposal. | Executed; proposed `plan_retrieval`. |
| `clarification` | Pause for missing user details. | Configured, not used. |
| `retrieval_review` | Review the retrieval intent before retrieval. | Executed; low-risk fast path allowed it. |
| `retrieval` | Run governed knowledge retrieval and evidence admission. | Executed; selected two documents and admitted two chunks. |
| `model_answer` | Generate and validate the final evidence-backed answer. | Executed; final answer model was called once. |
| `tool_review` | Review proposed governed tool calls. | Configured because tools are enabled, not used for this question. |
| `tool` | Execute or pause governed tool calls. | Configured because tools are enabled, not used for this question. |
| `memory` | Apply memory write policy. | Executed; wrote a case-scope summary. |
| `response` | Project the governed outcome to caller-facing output. | Executed; emitted final output. |

The LangGraph runtime is smaller than the public stage descriptor. The builder creates runtime graph nodes for `intent_resolution`, `plan`, `clarify`, `review_retrieval_plan`, `retrieval`, `model`, `review_tool`, and `tool`. In this run, the executed runtime path was:

```text
START
-> intent_resolution
-> plan
-> review_retrieval_plan
-> retrieval
-> model
-> END
```

`memory` and `response` are public Workflow Template Stages, but they are currently applied inside the `retrieval` and `model` runtime node handlers rather than scheduled as separate LangGraph nodes.

## Trace Shape

The run wrote 51 trace events. That count is not 51 workflow nodes. It is an audit trail made from setup, model resolution, stage context applications, policy decisions, review decisions, retrieval routing, validation, memory, and final output.

Event counts:

| Event type | Count |
| --- | ---: |
| `model_request` | 6 |
| `model_response` | 6 |
| `policy_decision` | 7 |
| `workflow_stage_context_applied` | 7 |
| `evidence_evaluation` | 4 |
| `model_connection_resolution` | 4 |
| `review_requested` | 3 |
| `review_decision` | 3 |
| all other event types | 1 each |

Execution grouping:

| Sequence range | Meaning |
| --- | --- |
| 1-4 | Run setup, manifest load, empty conversation context, stage configuration trace summary. |
| 5-8 | Shared DeepSeek model connection resolution for final answer, planner, intent resolution, and harness review roles. |
| 9-12 | Intent Resolution stage context, model call, and normalized intent facts. |
| 13-17 | Plan stage context, planner model call, reasoning summary, and action proposal. |
| 18-21 | Retrieval Review stage context, review request/decision, and policy allow. |
| 22-38 | Retrieval stage context, retrieval-step review, retrieval execution, Local Index routing model calls, retrieval result, evidence admission, and before-answer policy allow. |
| 39-40 | Memory stage context and memory write decision. |
| 41-49 | Model Answer stage context, before-model review, final answer model call, and schema/safety/citation validators. |
| 50-51 | Response stage context and final output. |

## Main Source of Extra Work

The main cost and latency source is retrieval routing, not the public Workflow Stage count.

The run made six remote model calls totaling 9,821 tokens:

| Role | Calls | Total tokens |
| --- | ---: | ---: |
| `intent_resolution` | 1 | 1,267 |
| `react_planner` | 1 | 1,115 |
| `routing` | 3 | 5,614 |
| `final_answer` | 1 | 1,825 |

The three `routing` calls happened because the `local_index` runtime provider first routed among four snapshot documents, selected two documents, and then queried each selected document's TreeIndex with `retriever_mode="select_leaf"`. Each selected document retrieval can use the source-owned routing model again through the LlamaIndex bridge.

The retrieval trace also shows all four document candidates had `metadata_matched: false`, including two generic `_.pdf` filenames. That forced model-based document routing instead of deterministic metadata narrowing.

## Optimization Recommendations

1. Preserve the Control Envelope, but clarify UI language.
   The Dashboard should distinguish configured stages, executed stages, trace events, and knowledge index nodes. Unexecuted branches such as `clarification`, `tool_review`, and `tool` should be shown as "configured / not visited" rather than implied run steps.

2. Emit or project executed stage results more explicitly.
   The runtime already carries `WorkflowStageResult` values in state, but production trace relies mostly on `workflow_stage_context_applied` for Dashboard projection. Add trace-safe stage result events or persist a trace-safe stage result projection so Run Detail can show status without guessing from context events.

3. Attach `stage_id` to more trace events.
   `model_request`, `model_response`, `review_requested`, `review_decision`, `retrieval_result`, `evidence_evaluation`, and `memory_write_decision` are stage-related but currently not all stage-addressed in the trace payload. Adding `stage_id` would reduce unassigned Timeline events and make the Workflow Lens easier to trust.

4. Improve Local Index routing metadata.
   Add product names, document titles, business categories, and aliases such as `平安御享` to document routing metadata. If metadata matching narrows candidates within budget, `route_snapshot_documents` can bypass the document-routing model call.

5. Benchmark replacing per-document `select_leaf` with a cheaper retrieval mode for small snapshots.
   For small selected document sets, `all_leaf` or a deterministic lexical/vector preselection may be faster and cheaper than a routing LLM call per selected revision. This is the highest-leverage runtime optimization for this run.

6. Add an entity-specific evidence sufficiency gate.
   The final answer says the evidence does not directly identify `平安御享`, but the outcome is still `ANSWERED_WITH_CITATIONS`. For product-comparison questions, a validator should require direct entity support or downgrade to a partial/insufficient-evidence outcome.

7. Consider a controlled fast path from Intent Resolution to Retrieval Review for simple knowledge queries.
   If Intent Resolution returns high-confidence `plan_retrieval`, no missing fields, no risk flags, and the action parameters are only the original query, the Control Plane could synthesize the same trace-safe action proposal without a second planner model call. This should be a descriptor-preserving optimization, not a topology change.

8. Do not optimize by deleting configured stages.
   The ten-stage descriptor is appropriate for an institution specialist Agent because it supports clarification, public knowledge retrieval, scoped read tools, approval, memory, and response projection. The excess in this run is mostly observability and retrieval routing work, not unnecessary public Workflow stages.
