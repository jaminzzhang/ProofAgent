from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value
from proof_agent.contracts.receipt import ReceiptOutcome


class EvaluationExecutionSurface(str, Enum):
    DIRECT_HARNESS = "direct_harness"
    RUN_EXECUTION_API = "run_execution_api"
    CUSTOMER_RUN_API = "customer_run_api"


class EvaluationExpectedResolution(str, Enum):
    ANSWER_WITH_CITATIONS = "answer_with_citations"
    REFUSE_NO_EVIDENCE = "refuse_no_evidence"
    ASK_CLARIFICATION = "ask_clarification"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    SAFE_HANDOFF = "safe_handoff"
    TOOL_APPROVAL_DENIED = "tool_approval_denied"


class EvaluationArtifactSufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    LOCAL_ONLY = "local_only"
    INSUFFICIENT = "insufficient"


class EvaluationGateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_EVALUATED = "not_evaluated"


class EvaluationGateAutomationLevel(str, Enum):
    AUTOMATED = "automated"
    SEMI_AUTOMATED = "semi_automated"
    DIAGNOSTIC = "diagnostic"


class EvaluationGateName(str, Enum):
    SUBJECT_MAPPING = "subject_mapping"
    ARTIFACT_SUFFICIENCY = "artifact_sufficiency"
    OUTCOME = "outcome"
    AUDIT_ARTIFACT = "audit_artifact"
    CONTROL_ENVELOPE_COVERAGE = "control_envelope_coverage"
    EVIDENCE_STRUCTURAL = "evidence_structural"
    TOOL_GOVERNANCE_STRUCTURAL = "tool_governance_structural"
    RESPONSE_PROJECTION_SAFETY = "response_projection_safety"
    REDACTION_SAFETY = "redaction_safety"
    RESPONSE_ASSERTION = "response_assertion"
    INTENT_EXECUTION_BEHAVIOR = "intent_execution_behavior"
    BUSINESS_FLOW_SKILL_PACK = "business_flow_skill_pack"
    FORBIDDEN_CLAIM = "forbidden_claim"


class EvaluationNodeStage(str, Enum):
    PLANNING = "planning"
    RETRIEVAL_EVIDENCE = "retrieval_evidence"
    POLICY_TOOL = "policy_tool"
    MODEL_VALIDATION = "model_validation"
    AUDIT_PROJECTION = "audit_projection"


class EvaluationScenarioLinkageMode(str, Enum):
    NONE = "none"
    SAME_CONVERSATION = "same_conversation"
    SAME_CONTINUATION_GROUP = "same_continuation_group"


class EvaluationFailureOwner(str, Enum):
    KNOWLEDGE_GAP = "knowledge_gap"
    RETRIEVAL_FAILURE = "retrieval_failure"
    PLANNING_FAILURE = "planning_failure"
    POLICY_FAILURE = "policy_failure"
    TOOL_GOVERNANCE_FAILURE = "tool_governance_failure"
    ANSWER_GENERATION_FAILURE = "answer_generation_failure"
    AUDIT_FAILURE = "audit_failure"
    LABEL_OR_CURATION_ISSUE = "label_or_curation_issue"
    JUDGE_DIAGNOSTIC_ISSUE = "judge_diagnostic_issue"


class EvaluationResponseProjectionAudience(str, Enum):
    OPERATOR = "operator"
    CUSTOMER = "customer"
    DIRECT = "direct"


class EvaluationReleaseDecisionStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class EvaluationResponseAssertions(FrozenModel):
    must_include_any: tuple[str, ...] = Field(default_factory=tuple)
    must_not_include: tuple[str, ...] = Field(default_factory=tuple)
    language: Literal["en", "zh"] | None = None


class EvaluationCaseExpected(FrozenModel):
    outcome: ReceiptOutcome
    required_citation_refs: tuple[str, ...] = Field(default_factory=tuple)
    required_tool_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    required_mcp_tool_names: tuple[str, ...] = Field(default_factory=tuple)
    required_tool_result_classifications: tuple[str, ...] = Field(default_factory=tuple)
    required_tool_failure_codes: tuple[str, ...] = Field(default_factory=tuple)
    expected_business_flow_skill_pack_decision: Literal[
        "admitted",
        "no_pack",
        "needs_clarification",
        "refused",
        "failed_closed",
    ] | None = None
    expected_business_flow_skill_pack_recommendation_type: Literal[
        "single_pack",
        "no_pack",
        "ambiguous",
    ] | None = None
    expected_business_flow_skill_pack_id: str | None = None
    forbid_clarification: bool = False
    max_action_constraint_rewrites: int | None = Field(default=None, ge=0)
    forbid_repeated_retrieval_queries: bool = False
    require_response_citation_refs: bool = False
    forbidden_claim_categories: tuple[str, ...] = Field(default_factory=tuple)
    required_business_claims: tuple[str, ...] = Field(default_factory=tuple)
    response_assertions: EvaluationResponseAssertions = Field(
        default_factory=EvaluationResponseAssertions
    )


class EvaluationQuestionMatch(FrozenModel):
    mode: Literal["exact_normalized", "accepted_variants", "intent_signature"] = (
        "exact_normalized"
    )
    accepted_variants: tuple[str, ...] = Field(default_factory=tuple)
    intent_signature: str | None = None


class EvaluationCase(FrozenModel):
    case_id: str
    question: str
    intent_type: str
    expected_resolution: EvaluationExpectedResolution
    risk_class: str
    capability_path: str
    expected: EvaluationCaseExpected
    required_for_release: bool = True
    question_match: EvaluationQuestionMatch = Field(default_factory=EvaluationQuestionMatch)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class EvaluationScenarioStep(FrozenModel):
    step_id: str
    case_id: str
    approval_event_ids: tuple[str, ...] = Field(default_factory=tuple)


class EvaluationScenarioLinkage(FrozenModel):
    mode: EvaluationScenarioLinkageMode = EvaluationScenarioLinkageMode.NONE


class EvaluationScenario(FrozenModel):
    scenario_id: str
    steps: tuple[EvaluationScenarioStep, ...]
    expected_ordered_outcomes: tuple[ReceiptOutcome, ...] = Field(default_factory=tuple)
    required_for_release: bool = True
    linkage: EvaluationScenarioLinkage = Field(default_factory=EvaluationScenarioLinkage)


class EvaluationSuite(FrozenModel):
    suite_id: str
    version: str
    name: str
    purpose: str = "smoke"
    gate_profile_id: str = "core_analyzer_gates.v1"
    cases: tuple[EvaluationCase, ...] = Field(default_factory=tuple)
    scenarios: tuple[EvaluationScenario, ...] = Field(default_factory=tuple)


class EvaluationCaseRef(FrozenModel):
    case_id: str
    scenario_id: str | None = None
    scenario_step_id: str | None = None


class EvaluationRunRef(FrozenModel):
    run_id: str | None = None
    source: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None


class EvaluationArtifactRef(FrozenModel):
    ref: Path
    sha256: str | None = None


class EvaluationResponseProjection(FrozenModel):
    audience: EvaluationResponseProjectionAudience
    ref: Path | None = None
    text: str | None = None
    sha256: str | None = None
    sensitivity: Literal["local_only", "release_safe"] | None = None


class EvaluationSubject(FrozenModel):
    case_ref: EvaluationCaseRef
    trace: EvaluationArtifactRef
    receipt: EvaluationArtifactRef
    run_meta: EvaluationArtifactRef | None = None
    response_projection: EvaluationResponseProjection
    execution_surface: EvaluationExecutionSurface = EvaluationExecutionSurface.DIRECT_HARNESS
    run_ref: EvaluationRunRef | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class EvaluationSubjectExportSelection(FrozenModel):
    case_ref: EvaluationCaseRef
    run_id: str
    response_projection_ref: Path
    response_projection_audience: EvaluationResponseProjectionAudience
    response_projection_sensitivity: Literal["local_only", "release_safe"] = "release_safe"
    execution_surface: EvaluationExecutionSurface = EvaluationExecutionSurface.RUN_EXECUTION_API


class EvaluationFrozenSubjectBundle(FrozenModel):
    bundle_id: str
    version: str
    suite_id: str
    suite_version: str
    subject_manifest_id: str
    subject_manifest_version: str
    bundle_dir: Path
    suite_path: Path
    subject_manifest_path: Path
    bundle_manifest_path: Path
    artifact_count: int


class EvaluationFrozenBundleVerification(FrozenModel):
    bundle_id: str
    status: Literal["passed", "failed"]
    checked_artifact_count: int
    missing_artifacts: tuple[str, ...] = Field(default_factory=tuple)
    mismatched_artifacts: tuple[str, ...] = Field(default_factory=tuple)
    suite_id: str | None = None
    subject_manifest_id: str | None = None


class EvaluationAnalysisRecord(FrozenModel):
    analysis_id: str
    suite_id: str
    subject_manifest_id: str
    release_decision_status: EvaluationReleaseDecisionStatus | None = None
    governed_resolution_rate: float = 0.0
    artifact_sufficiency_rate: float = 0.0
    failed_case_count: int = 0
    total_case_count: int = 0
    artifact_dir: Path


class EvaluationSubjectManifest(FrozenModel):
    manifest_id: str
    version: str
    suite_id: str
    subjects: tuple[EvaluationSubject, ...] = Field(default_factory=tuple)
    agent: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent", mode="after")
    @classmethod
    def freeze_agent(cls, value: Any) -> Any:
        return freeze_value(value)


class EvaluationGateResult(FrozenModel):
    gate: EvaluationGateName
    status: EvaluationGateStatus
    reason: str
    sufficiency: EvaluationArtifactSufficiencyStatus | None = None
    automation_level: EvaluationGateAutomationLevel = EvaluationGateAutomationLevel.AUTOMATED
    failure_owner: EvaluationFailureOwner | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class EvaluationGateProfile(FrozenModel):
    profile_id: str
    required_gates: tuple[EvaluationGateName, ...]
    diagnostic_gates: tuple[EvaluationGateName, ...] = Field(default_factory=tuple)


class EvaluationNodeResult(FrozenModel):
    stage: EvaluationNodeStage
    status: EvaluationGateStatus
    observed_events: tuple[str, ...] = Field(default_factory=tuple)
    key_facts: dict[str, Any] = Field(default_factory=dict)
    sufficiency: EvaluationArtifactSufficiencyStatus | None = None
    failure_owner: EvaluationFailureOwner | None = None

    @field_validator("key_facts", mode="after")
    @classmethod
    def freeze_key_facts(cls, value: Any) -> Any:
        return freeze_value(value)


class EvaluationArtifactSummary(FrozenModel):
    ref: Path | None = None
    declared_sha256: str | None = None
    observed_sha256: str | None = None


class EvaluationResponseProjectionSummary(FrozenModel):
    audience: EvaluationResponseProjectionAudience
    ref: Path | None = None
    declared_sha256: str | None = None
    observed_text_sha256: str | None = None
    text_length: int = 0
    source: Literal["file", "inline"] = "file"
    sensitivity: Literal["local_only", "release_safe"] | None = None


class EvaluationCaseResult(FrozenModel):
    case_id: str
    status: EvaluationGateStatus
    expected_outcome: ReceiptOutcome
    actual_outcome: ReceiptOutcome | None = None
    subject_present: bool = True
    scenario_id: str | None = None
    scenario_step_id: str | None = None
    gates: tuple[EvaluationGateResult, ...] = Field(default_factory=tuple)
    node_results: tuple[EvaluationNodeResult, ...] = Field(default_factory=tuple)
    trace: EvaluationArtifactSummary | None = None
    receipt: EvaluationArtifactSummary | None = None
    run_meta: EvaluationArtifactSummary | None = None
    response_projection: EvaluationResponseProjectionSummary | None = None
    artifact_sufficiency: EvaluationArtifactSufficiencyStatus | None = None
    primary_failure_owner: EvaluationFailureOwner | None = None
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class EvaluationScenarioResult(FrozenModel):
    scenario_id: str
    status: EvaluationGateStatus
    expected_ordered_outcomes: tuple[str, ...] = Field(default_factory=tuple)
    actual_ordered_outcomes: tuple[str, ...] = Field(default_factory=tuple)
    step_results: tuple[EvaluationCaseResult, ...] = Field(default_factory=tuple)
    failed_step_ids: tuple[str, ...] = Field(default_factory=tuple)
    linkage_status: EvaluationGateStatus = EvaluationGateStatus.PASSED
    linkage_reason: str | None = None
    approval_linkage_status: EvaluationGateStatus = EvaluationGateStatus.PASSED
    approval_linkage_reason: str | None = None


class EvaluationReleaseDecision(FrozenModel):
    decision_profile_id: str = "core_analyzer_release.v1"
    status: EvaluationReleaseDecisionStatus
    required_case_pass_rate: float
    required_case_pass_threshold: float = 1.0
    required_artifact_sufficiency_rate: float
    artifact_sufficiency_threshold: float = 1.0
    required_deterministic_gate_pass_rate: float
    deterministic_gate_pass_threshold: float = 1.0
    required_scenario_pass_rate: float | None = None
    scenario_pass_threshold: float | None = None
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)


class EvaluationAnalysisSummary(FrozenModel):
    analyzer_version: str = "evaluation-analyzer.v1"
    analysis_id: str
    suite_id: str
    suite_version: str
    subject_manifest_id: str
    subject_manifest_version: str
    gate_profile_id: str
    total_required_cases: int
    passed_required_cases: int
    governed_resolution_rate: float
    subject_coverage_rate: float
    artifact_sufficiency_rate: float
    deterministic_gate_pass_rate: float
    case_results: tuple[EvaluationCaseResult, ...] = Field(default_factory=tuple)
    scenario_results: tuple[EvaluationScenarioResult, ...] = Field(default_factory=tuple)
    scenario_governed_resolution_rate: float = 0.0
    release_decision: EvaluationReleaseDecision
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    behavior_metrics: dict[str, float] = Field(default_factory=dict)
    agent: dict[str, Any] = Field(default_factory=dict)
    artifact_dir: Path | None = None
    judge_mode: Literal["none"] = "none"

    @field_validator("behavior_metrics", mode="after")
    @classmethod
    def freeze_behavior_metrics(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator("agent", mode="after")
    @classmethod
    def freeze_agent(cls, value: Any) -> Any:
        return freeze_value(value)
