from pathlib import Path

import pytest

from proof_agent.bootstrap import compose_harness_invocation
from proof_agent.contracts import (
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")


def _kss_bindings() -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeSourceServiceBinding(
                binding_id="enterprise-knowledge",
                knowledge_base_release_id="release-enterprise-2026-08-18",
                client_credential_ref=ProductionSecretHandle(
                    protocol_id="vault-kv-v2",
                    handle_id="knowledge/source-service/enterprise-client",
                    purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                    version_id="credential-v4",
                ),
                admission_scorer_id="enterprise-evidence-admission",
                admission_scorer_revision="enterprise-evidence-admission.v2",
            ),
        )
    )


def test_compose_harness_invocation_resolves_non_knowledge_dependencies() -> None:
    invocation = compose_harness_invocation(AGENT)

    assert invocation.manifest.name == "react_enterprise_qa_v3"
    assert invocation.template.name == "react_enterprise_qa_v3"
    assert invocation.model_provider.provider_name == "deterministic"
    assert invocation.resolved_knowledge_bindings.bindings == ()
    assert invocation.knowledge_candidate_service is None
    assert invocation.tool_gateway.tools == {}
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None


def test_composition_preserves_exact_kss_runtime_dependencies() -> None:
    candidate_service = object()
    query_factory = object()
    admission_scorer = object()
    bindings = _kss_bindings()

    invocation = compose_harness_invocation(
        AGENT,
        resolved_knowledge_bindings=bindings,
        knowledge_candidate_service=candidate_service,
        knowledge_candidate_query_factory=query_factory,
        knowledge_candidate_admission_scorer=admission_scorer,
    )

    assert invocation.resolved_knowledge_bindings is bindings
    assert invocation.knowledge_candidate_service is candidate_service
    assert invocation.knowledge_candidate_query_factory is query_factory
    assert invocation.knowledge_candidate_admission_scorer is admission_scorer


def test_composition_rejects_kss_runtime_without_published_binding() -> None:
    with pytest.raises(ProofAgentError, match="requires one exact Published KSS binding"):
        compose_harness_invocation(
            AGENT,
            knowledge_candidate_service=object(),
            knowledge_candidate_query_factory=object(),
            knowledge_candidate_admission_scorer=object(),
        )


def test_composition_rejects_binding_without_kss_runtime() -> None:
    with pytest.raises(ProofAgentError, match="has no executable Candidate runtime"):
        compose_harness_invocation(
            AGENT,
            resolved_knowledge_bindings=_kss_bindings(),
        )


def test_unknown_workflow_template_fails_from_registry() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_workflow_template("unknown_template")

    assert exc.value.code == "PA_CONFIG_002"


def test_react_workflow_template_resolves_from_registry() -> None:
    assert resolve_workflow_template("react_enterprise_qa_v3").name == (
        "react_enterprise_qa_v3"
    )
