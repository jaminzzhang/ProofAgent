from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from proof_agent.contracts._base import FrozenModel, freeze_value
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.insurance_rules import InsuranceEvidenceSlotRequirement


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


InsuranceKnowledgeQueryType = Literal[
    "clause_lookup",
    "conditional_guidance",
    "comparison",
]


class InsuranceKnowledgeCase(FrozenModel):
    """One exact gold case for governed insurance Knowledge evaluation."""

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    query_type: InsuranceKnowledgeQueryType
    source_id: str = Field(min_length=1)
    source_publication_id: str = Field(min_length=1)
    source_publication_seq: int = Field(gt=0)
    required_rule_unit_revision_ids: tuple[str, ...] = ()
    required_evidence_slots: tuple[InsuranceEvidenceSlotRequirement, ...] = ()
    expected_resolution: EvaluationExpectedResolution
    expected_knowledge_outcome: Literal[
        "answer_with_citations",
        "ask_clarification",
        "conflict",
        "refuse_no_evidence",
        "no_recommendation",
    ] = "answer_with_citations"
    expected_authority_outcome: Literal["PASS", "FAIL", "CONFLICT"] = "PASS"
    normalized_conditions: Mapping[str, str] = Field(default_factory=dict)
    expected_clarification_fields: tuple[str, ...] = ()
    required_warning_codes: tuple[str, ...] = ()
    acl_hard_negative_rule_unit_revision_ids: tuple[str, ...] = ()
    document_slice: str = "unspecified"
    parser_slice: str = "unspecified"
    acl_slice: str = "public"

    @field_validator("normalized_conditions", mode="after")
    @classmethod
    def freeze_conditions(cls, value: Any) -> Any:
        return freeze_value(value)

    @model_validator(mode="after")
    def require_comparison_slots(self) -> InsuranceKnowledgeCase:
        if self.query_type == "comparison" and len(self.required_evidence_slots) < 2:
            raise ValueError("comparison cases require at least two evidence slots")
        if (
            self.expected_knowledge_outcome == "answer_with_citations"
            and not self.required_rule_unit_revision_ids
        ):
            raise ValueError("answered cases require gold Rule Unit revisions")
        if (
            self.expected_knowledge_outcome == "answer_with_citations"
            and not self.required_evidence_slots
        ):
            raise ValueError("answered cases require gold evidence slots")
        rule_ids = self.required_rule_unit_revision_ids
        slot_ids = tuple(slot.slot_id for slot in self.required_evidence_slots)
        hard_negatives = self.acl_hard_negative_rule_unit_revision_ids
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("gold Rule Unit revisions must be unique")
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("gold evidence slot ids must be unique")
        if set(rule_ids).intersection(hard_negatives):
            raise ValueError("ACL hard negatives must not overlap gold Rule Units")
        if (
            self.expected_knowledge_outcome == "ask_clarification"
            and not self.expected_clarification_fields
        ):
            raise ValueError("clarification cases require explicit clarification fields")
        return self


class InsuranceRetrievalMetrics(FrozenModel):
    """Ranking facts for one insurance Knowledge evaluation cohort."""

    retrieval_case_count: int = Field(ge=0)
    required_evidence_recall_at_20: float = Field(ge=0.0, le=1.0)
    required_evidence_recall_at_50: float = Field(ge=0.0, le=1.0)
    required_evidence_recall_at_100: float = Field(ge=0.0, le=1.0)
    complete_evidence_top_5_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    complete_evidence_top_10_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    ndcg_at_10: float = Field(default=0.0, ge=0.0, le=1.0)
    mrr_at_10: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_resolvability_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    authority_failure_count: int = Field(default=0, ge=0)
    unauthorized_candidate_exposure: int = Field(default=0, ge=0)


class InsuranceKnowledgeObservation(FrozenModel):
    """Trace-safe observed retrieval facts for one labeled case."""

    case_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_publication_id: str = Field(min_length=1)
    source_publication_seq: int = Field(gt=0)
    ranked_rule_unit_revision_ids: tuple[str, ...]
    evidence_slot_ranks: Mapping[str, int] = Field(default_factory=dict)
    resolvable_citation_rule_unit_revision_ids: tuple[str, ...] = ()
    authority_failure_count: int = Field(default=0, ge=0)

    @field_validator("evidence_slot_ranks", mode="after")
    @classmethod
    def freeze_slot_ranks(cls, value: Any) -> Any:
        if any(type(rank) is not int or rank <= 0 for rank in value.values()):
            raise ValueError("evidence slot ranks must be positive integers")
        return freeze_value(value)

    @model_validator(mode="after")
    def require_unique_ranked_identities(self) -> InsuranceKnowledgeObservation:
        if len(self.ranked_rule_unit_revision_ids) != len(set(self.ranked_rule_unit_revision_ids)):
            raise ValueError("ranked Rule Unit identities must be unique")
        return self


class InsuranceKnowledgeSliceMetrics(FrozenModel):
    dimension: Literal["query_type", "document", "parser", "acl"]
    value: str = Field(min_length=1)
    case_count: int = Field(gt=0)
    metrics: InsuranceRetrievalMetrics


class InsuranceKnowledgeEvaluationReport(FrozenModel):
    case_count: int = Field(gt=0)
    overall: InsuranceRetrievalMetrics
    slices: tuple[InsuranceKnowledgeSliceMetrics, ...]


class ParserExpectedTableCell(FrozenModel):
    table_id: str = Field(min_length=1)
    page_number: int = Field(gt=0)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str = Field(min_length=1)


class InsuranceParserCase(FrozenModel):
    """Gold structural and OCR expectations for one document revision."""

    case_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    document_slice: str = Field(min_length=1)
    parser_slice: str = Field(min_length=1)
    query_slice: InsuranceKnowledgeQueryType
    acl_slice: str = Field(min_length=1)
    expected_reading_order: tuple[str, ...] = ()
    expected_table_cells: tuple[ParserExpectedTableCell, ...] = ()
    expected_cross_page_continuation_ids: tuple[str, ...] = ()
    expected_ocr_text: str = ""
    expected_citation_anchors: tuple[str, ...] = ()
    mandatory_review_expected: bool

    @model_validator(mode="after")
    def require_parser_gold(self) -> InsuranceParserCase:
        if not any(
            (
                self.expected_reading_order,
                self.expected_table_cells,
                self.expected_cross_page_continuation_ids,
                self.expected_ocr_text,
                self.expected_citation_anchors,
            )
        ):
            raise ValueError("parser case requires at least one gold expectation")
        return self


class InsuranceParserObservation(FrozenModel):
    case_id: str = Field(min_length=1)
    observed_reading_order: tuple[str, ...] = ()
    observed_table_cells: tuple[ParserExpectedTableCell, ...] = ()
    observed_cross_page_continuation_ids: tuple[str, ...] = ()
    observed_ocr_text: str = ""
    observed_citation_anchors: tuple[str, ...] = ()
    review_required: bool


class ParserBenchmarkMetrics(FrozenModel):
    character_recall: float = Field(ge=0.0, le=1.0)
    reading_order_recall: float = Field(ge=0.0, le=1.0)
    table_cell_recall: float = Field(ge=0.0, le=1.0)
    cross_page_continuation_recall: float = Field(ge=0.0, le=1.0)
    citation_anchor_recall: float = Field(ge=0.0, le=1.0)
    review_required_recall: float = Field(ge=0.0, le=1.0)


class ParserBenchmarkSliceMetrics(FrozenModel):
    dimension: Literal["query_type", "document", "parser", "acl"]
    value: str = Field(min_length=1)
    case_count: int = Field(gt=0)
    metrics: ParserBenchmarkMetrics


class ParserBenchmarkReport(FrozenModel):
    case_count: int = Field(gt=0)
    overall: ParserBenchmarkMetrics
    slices: tuple[ParserBenchmarkSliceMetrics, ...]


class InsuranceKnowledgeGoldSuite(FrozenModel):
    """Human-confirmed insurance Knowledge cases with the fixed query profile."""

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: tuple[InsuranceKnowledgeCase, ...] = Field(min_length=10)

    @model_validator(mode="after")
    def require_query_profile(self) -> InsuranceKnowledgeGoldSuite:
        total = len(self.cases)
        case_ids = tuple(case.case_id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("insurance Knowledge suite case ids must be unique")
        counts = {
            query_type: sum(case.query_type == query_type for case in self.cases)
            for query_type in ("clause_lookup", "conditional_guidance", "comparison")
        }
        if not (
            counts["clause_lookup"] * 10 == total * 3
            and counts["conditional_guidance"] * 10 == total * 5
            and counts["comparison"] * 10 == total * 2
        ):
            raise ValueError("insurance Knowledge suite requires the 30/50/20 query mix")
        return self


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
    TOOL_PROPOSAL_SCOPE = "tool_proposal_scope"
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


class EvaluationCampaignReadinessStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class EvaluationCampaignCapabilityStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_COVERED = "not_covered"


class EvaluationDiagnosticFinding(FrozenModel):
    severity: Literal["low", "medium", "high"]
    category: str
    summary: str


class EvaluationCaseDiagnostic(FrozenModel):
    case_id: str
    status: Literal["passed_with_diagnostics", "needs_review"]
    quality_score: float
    findings: tuple[EvaluationDiagnosticFinding, ...] = Field(default_factory=tuple)
    diagnostic_blocker_candidate: bool = False


class EvaluationCampaignDiagnostics(FrozenModel):
    diagnostics_version: str = "coding-agent-diagnostics.v1"
    evaluated_case_count: int = 0
    mean_quality_score: float | None = None
    diagnostic_blocker_candidate_count: int = 0
    case_diagnostics: tuple[EvaluationCaseDiagnostic, ...] = Field(default_factory=tuple)


class EvaluationDiagnosticInputCase(FrozenModel):
    case_id: str
    expected_outcome: str
    actual_outcome: str | None = None
    status: str
    primary_failure_owner: str | None = None
    response_projection: EvaluationResponseProjectionSummary | None = None
    gate_results: tuple[dict[str, str | None], ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class EvaluationDiagnosticInputBundle(FrozenModel):
    diagnostics_input_version: str = "coding-agent-diagnostics-input.v1"
    campaign_id: str
    version: str
    target_agent_id: str
    target_agent_version_id: str | None = None
    readiness_status: str
    governed_resolution_rate: float
    artifact_sufficiency_rate: float
    deterministic_gate_pass_rate: float
    cases: tuple[EvaluationDiagnosticInputCase, ...] = Field(default_factory=tuple)


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
    required_tool_proposal_scope_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    forbidden_tool_proposal_scope_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    expect_empty_tool_proposal_scope: bool = False
    expected_business_flow_skill_pack_decision: (
        Literal[
            "admitted",
            "no_pack",
            "needs_clarification",
            "refused",
            "failed_closed",
        ]
        | None
    ) = None
    expected_business_flow_skill_pack_recommendation_type: (
        Literal[
            "single_pack",
            "no_pack",
            "ambiguous",
        ]
        | None
    ) = None
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
    mode: Literal["exact_normalized", "accepted_variants", "intent_signature"] = "exact_normalized"
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
    continuation_group_id: str | None = None


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


class EvaluationCampaignSuiteRun(FrozenModel):
    source: str
    suite_id: str
    suite_version: str
    analysis_id: str
    release_decision_status: EvaluationReleaseDecisionStatus
    total_required_cases: int
    passed_required_cases: int
    governed_resolution_rate: float
    artifact_dir: Path | None = None


class EvaluationCampaignCapabilityCoverage(FrozenModel):
    capability_path: str
    status: EvaluationCampaignCapabilityStatus
    required_cases: int
    passed_required_cases: int
    failed_required_cases: int


class EvaluationCampaignSummary(FrozenModel):
    campaign_id: str
    version: str
    target_agent_id: str
    target_agent_version_id: str | None = None
    readiness_status: EvaluationCampaignReadinessStatus
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    governed_resolution_rate: float
    artifact_sufficiency_rate: float
    deterministic_gate_pass_rate: float
    suite_runs: tuple[EvaluationCampaignSuiteRun, ...] = Field(default_factory=tuple)
    capability_coverage: tuple[EvaluationCampaignCapabilityCoverage, ...] = Field(
        default_factory=tuple
    )
    artifact_dir: Path
    coding_agent_diagnostics: EvaluationCampaignDiagnostics | None = None
