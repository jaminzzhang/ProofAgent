import json
import pytest

from proof_agent.capabilities.knowledge.dify import DifyKnowledgeProvider
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


def record_payload():
    return {
        "schema_version": "proofagent-structured-evidence.v1",
        "record_id": "claim-2025",
        "fields": [
            {"field": "claim_total", "value_type": "decimal", "value": "12345.6700", "unit": "CNY"},
            {"field": "count", "value_type": "integer", "value": 9007199254740993},
            {"field": "approved", "value_type": "boolean", "value": False},
            {"field": "expiry", "value_type": "null", "value": None},
        ],
    }


def provider_for_content(content, *, content_format="structured_json", answer=None):
    class Http:
        def request(self, method, url, **kwargs):
            payload = {
                "query": json.loads(kwargs["body"])["query"],
                "records": [
                    {
                        "score": 0.95,
                        "segment": {
                            "id": "segment-1",
                            "document_id": "document-1",
                            "enabled": True,
                            "status": "completed",
                            "content": content,
                            "answer": answer,
                        },
                    }
                ],
            }
            return GuardedHttpResponse(
                200, {"content-type": "application/json"}, json.dumps(payload).encode()
            )

    binding = ExternalKnowledgeBinding.model_validate(
        {
            "binding_id": "claims",
            "provider": "dify",
            "endpoint": "https://dify.example/v1",
            "dataset_id": "c42e2a6e-40b3-4330-96f8-f1e4d768e8c9",
            "content_format": content_format,
            "credential_ref": {
                "protocol_id": "local-environment-v1",
                "handle_id": "KEY",
                "purpose": "knowledge_credential",
                "version_id": "env",
            },
        }
    )
    return DifyKnowledgeProvider(
        binding=binding,
        http_client=Http(),
        secret_provider=LocalEnvironmentSecretProvider({"KEY": "synthetic"}, mode="development"),
    )


def test_dify_structured_record_preserves_exact_values_without_admitting_them():
    payload = record_payload()
    candidate = provider_for_content(json.dumps(payload)).query("Claim total?").candidates[0]
    record = candidate.structured_data
    assert record.record_id == "claim-2025"
    assert record.fields[0].value == "12345.6700" and record.fields[0].unit == "CNY"
    assert type(record.fields[1].value) is int and record.fields[1].value == 9007199254740993
    assert record.fields[2].value is False and record.fields[3].value is None
    assert candidate.document_id == "document-1" and candidate.chunk_id == "segment-1"
    assert not hasattr(candidate, "admission_score")
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    "kind,value",
    [
        ("decimal", 123.45),
        ("decimal", "NaN"),
        ("decimal", "Infinity"),
        ("decimal", "1e2"),
        ("decimal", " 12.00"),
        ("decimal", "9" * 129),
        ("integer", True),
        ("integer", "123"),
        ("integer", 1.5),
        ("integer", 10**129),
        ("boolean", 1),
        ("boolean", "false"),
        ("string", 123),
        ("null", "null"),
        ("date", "2025-02-30"),
        ("date", "20250101"),
        ("datetime", "2025-01-01T00:00:00"),
        ("datetime", "not-a-date"),
    ],
)
def test_mistyped_or_unbounded_fields_fail_without_text_fallback(kind, value):
    from proof_agent.errors import ProofAgentError

    record = record_payload()
    record["fields"][0].update(value_type=kind, value=value)
    with pytest.raises(ProofAgentError, match="response_invalid"):
        provider_for_content(json.dumps(record)).query("Claim total?")


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_field",
        "duplicate_key",
        "unknown",
        "version",
        "missing_version",
        "too_many",
        "empty",
        "qa",
    ],
)
def test_ambiguous_structured_content_fails_closed(change):
    from proof_agent.errors import ProofAgentError

    record = record_payload()
    if change == "duplicate_field":
        record["fields"].append(record["fields"][0])
    if change == "unknown":
        record["admitted"] = True
    if change == "version":
        record["schema_version"] = "proofagent-structured-evidence.v2"
    if change == "missing_version":
        record.pop("schema_version")
    if change == "too_many":
        record["fields"] = [
            {"field": f"f{i}", "value_type": "null", "value": None} for i in range(65)
        ]
    if change == "empty":
        record["fields"] = []
    content = json.dumps(record)
    if change == "duplicate_key":
        content = content.replace(
            '"value": "12345.6700"', '"value": "wrong", "value": "12345.6700"'
        )
    with pytest.raises(ProofAgentError, match="response_invalid"):
        provider_for_content(content, answer=" " if change == "qa" else None).query("Claim total?")


def test_text_mode_never_promotes_json_into_structured_evidence():
    content = json.dumps(record_payload())
    candidate = (
        provider_for_content(content, content_format="text").query("Claim total?").candidates[0]
    )
    assert candidate.content == content and candidate.structured_data is None


def answer_records(request):
    content = request.messages[1].content
    if content.startswith("{"):
        return json.loads(content)["accepted_evidence"]
    return json.loads(content.split("Evidence:\n", 1)[1].split("\n\nAllowed citation refs:", 1)[0])


def test_real_harness_preserves_typed_facts_original_constraints_and_required_rewrite():
    from proof_agent.evaluation.demo.kernel_probes import exercise_retrieval

    question = "Compare 2025 claims in CNY; do not include 2024 or convert currencies."
    query = "claim_total year 2025 currency CNY"
    observation = exercise_retrieval(
        question=question, queries=(), intent_queries=(query,), structured=True
    )
    assert observation.queries == (query,)
    evidence = observation.admitted_evidence[0]
    assert evidence.structured_data.fields[0].value == "12345.67"
    assert len(observation.answer_requests) == 2
    assert observation.answer_requests[1].metadata["repair_attempt"] == 1
    for request in observation.answer_requests:
        assert question in request.messages[1].content
        record = answer_records(request)[0]
        assert record["structured_data"] == evidence.structured_data.model_dump(mode="json")
        assert record["source"] == evidence.source
        assert record["citation"] == evidence.citation
        assert record["source_version_id"] == evidence.source_version_id
        assert record["document_id"] == evidence.document_id == "source-table-1"


def accepted_chunk(*, document="document-1", value="12345.6700"):
    from proof_agent.contracts import EvidenceChunk, EvidenceStatus

    payload = record_payload()
    payload["fields"][0]["value"] = value
    candidate = provider_for_content(json.dumps(payload)).query("Claim total?").candidates[0]
    source = f"external://claims/datasets/dataset-1/documents/{document}"
    return EvidenceChunk(
        source=source,
        citation=f"{source}#segment=segment-1&sha256={candidate.content_sha256}",
        content=candidate.content,
        status=EvidenceStatus.ACCEPTED,
        binding_id="claims",
        source_id="dataset-1",
        document_id=document,
        chunk_id="segment-1",
        source_version_id=f"sha256:{candidate.content_sha256}",
        structured_data=candidate.structured_data,
        admission_score=1.0,
    )


def test_answer_input_keeps_conflicting_records_separate_and_excludes_unadmitted_data():
    from proof_agent.contracts import EvidenceStatus
    from proof_agent.control.workflow.harness_helpers import build_model_request

    first = accepted_chunk()
    second = accepted_chunk(document="document-2", value="500.00")
    rejected = accepted_chunk(document="hidden", value="999.99").model_copy(
        update={"status": EvidenceStatus.REJECTED}
    )
    candidate = rejected.model_copy(update={"status": EvidenceStatus.CANDIDATE})
    request = build_model_request(
        question="Compare",
        evidence=(first, rejected, second, candidate),
        provider="deterministic",
        model="test",
    )
    records = answer_records(request)
    assert [record["structured_data"]["fields"][0]["value"] for record in records] == [
        "12345.6700",
        "500.00",
    ]
    assert [record["citation"] for record in records] == [first.citation, second.citation]
    assert request.evidence_sources == (first.source, second.source)
    prompt = "\n".join(message.content for message in request.messages)
    assert "999.99" not in prompt and "hidden" not in prompt


@pytest.mark.parametrize(
    "change",
    [
        "content",
        "record",
        "unit",
        "citation",
        "version",
        "document",
        "binding",
        "dataset",
        "segment",
    ],
)
def test_tampered_typed_evidence_is_rejected_before_answer_input(change):
    from proof_agent.control.workflow.harness_helpers import build_model_request
    from proof_agent.errors import ProofAgentError

    chunk = accepted_chunk()
    updates = {
        "content": {"content": chunk.content.replace("12345.6700", "500.0000")},
        "record": {"structured_data": accepted_chunk(value="500.00").structured_data},
        "unit": {
            "structured_data": chunk.structured_data.model_copy(
                update={
                    "fields": (
                        chunk.structured_data.fields[0].model_copy(update={"unit": "USD"}),
                        *chunk.structured_data.fields[1:],
                    )
                }
            )
        },
        "citation": {"citation": "external://another-source"},
        "version": {"source_version_id": "sha256:" + "0" * 64},
        "document": {"document_id": "another-document"},
        "binding": {"binding_id": "another-binding"},
        "dataset": {"source_id": "another-dataset"},
        "segment": {"chunk_id": "another-segment"},
    }
    with pytest.raises(ProofAgentError, match="integrity check failed"):
        build_model_request(
            question="Compare",
            evidence=(chunk.model_copy(update=updates[change]),),
            provider="deterministic",
            model="test",
        )


def test_legacy_text_serialization_does_not_change_existing_bound_truth():
    from proof_agent.contracts import EvidenceChunk, EvidenceStatus, RetrievalObservationTruth
    from proof_agent.control.workflow.controlled_react.artifact_binding import (
        bind_observation_truth,
        model_payload,
    )

    chunk = EvidenceChunk(
        source="old", citation="old#1", content="Old content", status=EvidenceStatus.ACCEPTED
    )
    old_payload = chunk.model_dump(mode="python", warnings=False)
    assert "structured_data" not in old_payload
    truth = RetrievalObservationTruth(
        truth_ref="observation://legacy/obs1/truth",
        observation_id="obs1",
        action_id="act1",
        accepted_evidence=(chunk,),
    )
    binding = bind_observation_truth(truth)
    recovered = RetrievalObservationTruth.model_validate_json(
        json.dumps(model_payload(binding.truth))
    )
    assert bind_observation_truth(recovered).reference == binding.reference


def test_stored_truth_reconstruction_preserves_types_and_rejects_rebound_content(tmp_path):
    from proof_agent.contracts import RetrievalObservationTruth
    from proof_agent.control.workflow.controlled_react.artifact_binding import (
        bind_observation_truth,
        model_payload,
    )
    from proof_agent.control.workflow.controlled_react.local_stores import FileObservationTruthStore
    from proof_agent.control.workflow.harness_helpers import build_model_request
    from proof_agent.errors import ProofAgentError

    chunk = accepted_chunk()
    truth = RetrievalObservationTruth(
        truth_ref="observation://typed/obs1/truth",
        observation_id="obs1",
        action_id="act1",
        accepted_evidence=(chunk,),
        citation_refs=(chunk.citation,),
    )
    binding = bind_observation_truth(truth)
    ref = FileObservationTruthStore(tmp_path).save(binding.truth)
    recovered = FileObservationTruthStore(tmp_path).load(ref)
    request = build_model_request(
        question="Restore",
        evidence=recovered.accepted_evidence,
        provider="deterministic",
        model="test",
    )
    assert answer_records(request)[0]["structured_data"] == chunk.structured_data.model_dump(
        mode="json"
    )
    # Even internally consistent replacement content must not reuse the old truth reference.
    changed = accepted_chunk(value="500.00")
    payload = model_payload(binding.truth)
    payload["accepted_evidence"] = [model_payload(changed)]
    payload["citation_refs"] = [changed.citation]
    (tmp_path / "typed/controlled_react/observation_truth/obs1.json").write_text(
        json.dumps(payload)
    )
    with pytest.raises(ProofAgentError):
        FileObservationTruthStore(tmp_path).load(ref)


@pytest.mark.parametrize("expected_format", ["text", "structured_json"])
def test_control_plane_rejects_provider_format_drift(expected_format):
    from pathlib import Path
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeResult
    from proof_agent.control.knowledge.retrieval_service import (
        KnowledgeRetrievalService,
        KnowledgeRetrievalRequest,
    )
    from proof_agent.control.policy.engine import PolicyEngine
    from proof_agent.errors import ProofAgentError

    binding = ExternalKnowledgeBinding(
        binding_id="claims",
        provider="dify",
        endpoint="https://dify.example/v1",
        dataset_id="c42e2a6e-40b3-4330-96f8-f1e4d768e8c9",
        content_format=expected_format,
        credential_ref={
            "protocol_id": "local-environment-v1",
            "handle_id": "KEY",
            "purpose": "knowledge_credential",
            "version_id": "env",
        },
    )
    other_format = "text" if expected_format == "structured_json" else "structured_json"
    candidate = (
        provider_for_content(json.dumps(record_payload()), content_format=other_format)
        .query("Claim total?")
        .candidates[0]
    )

    class Sources:
        bindings = (binding,)

        def query(self, binding_id, question):
            return ExternalKnowledgeResult(
                binding_id=binding_id, query=question, candidates=(candidate,)
            )

    class Trace:
        def emit(self, *args, **kwargs):
            pass

    service = KnowledgeRetrievalService(
        trace=Trace(),
        policy=PolicyEngine.from_file(
            Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/policy.yaml")
        ),
        knowledge_candidate_service=None,
        external_knowledge=Sources(),
    )
    with pytest.raises(ProofAgentError, match="format"):
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="Claim total?", strategy="single_step", top_k=3, min_score=0.2
            )
        )


def test_answer_attempt_prepares_only_accepted_records_for_later_repair():
    from types import SimpleNamespace
    from proof_agent.contracts import AnswerEvidenceContext, ControlledReActRunState, EvidenceStatus
    from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
        FinalAnswerAttemptRunner,
    )
    from proof_agent.evaluation.demo.kernel_probes import ScriptedModelProvider

    accepted = accepted_chunk()
    candidate = accepted_chunk(document="unadmitted").model_copy(
        update={"status": EvidenceStatus.CANDIDATE}
    )
    runner = FinalAnswerAttemptRunner(
        SimpleNamespace(model_provider=ScriptedModelProvider(("{}",))), trace=None
    )
    state = ControlledReActRunState(
        run_id="typed",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="Claim total?",
    )
    prepared = runner.prepare(
        state, AnswerEvidenceContext(run_id="typed"), evidence=(accepted, candidate)
    )
    assert prepared.evidence == (accepted,)
    assert prepared.request.evidence_sources == (accepted.source,)
    assert "unadmitted" not in prepared.request.messages[1].content
