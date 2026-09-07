"""Two domain packages drive the same V3 and real Dify adapter with synthetic HTTP."""
from dataclasses import replace
from pathlib import Path
import json

import pytest

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
from proof_agent.contracts import (BusinessFlowCandidatePack, BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType, IntentResolutionResult, ReActActionType, ReceiptOutcome,
    RetrievalQueryItem)
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.control.workflow.controlled_react.composition import build_controlled_react_orchestrator_for_invocation
from proof_agent.delivery.agent_package_execution import AgentPackageRunRequest, execute_agent_package_run
from test_tool_task_gateway_integration import TaskIntent


@pytest.mark.parametrize('path,pack_id,question,fact', [
    ('examples/agent_management_insurance_specialist/agent.yaml', 'claims_consultation',
     'What is the reimbursement limit?', 'Reimbursement limit is 100 yuan.'),
    ('proof_agent/evaluation/demo/fixtures/it_service_desk/agent.yaml', 'password_reset',
     'What is required for employee account recovery?', 'Account recovery requires a verified employee session.'),
])
def test_two_domains_use_original_v3_admission_and_retrieval(tmp_path, path, pack_id, question, fact):
    class Intent(TaskIntent):
        def resolve(self, **kwargs):
            resolution = super().resolve(**kwargs).intent_resolution.model_copy(update={
                'recommended_next_action': ReActActionType.PLAN_RETRIEVAL,
                'retrieval_query_set': (RetrievalQueryItem(query=question, intent_angle='policy', required=True, reason='Required policy'),)})
            return IntentResolutionResult(intent_resolution=resolution,
                business_flow_skill_pack_recommendation=BusinessFlowSkillPackRecommendation(
                    recommendation_id='domain-route', intent_resolution_id=resolution.resolution_id,
                    recommendation_type=BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
                    confidence=1, reason='Fixed domain route', candidate_packs=(BusinessFlowCandidatePack(
                        pack_id=pack_id, confidence=1, reason='Matching domain'),)))
    queries = []
    class Http:
        def request(self, method, url, **kwargs):
            queries.append(json.loads(kwargs['body'])['query'])
            return GuardedHttpResponse(status_code=200, headers={'content-type': 'application/json'}, body=json.dumps({'query': queries[-1], 'records': [
                {'score': .95, 'segment': {'id': 'policy_segment', 'document_id': 'policy_document',
                    'enabled': True, 'status': 'completed', 'content': fact, 'document': {'id': 'policy_document', 'name': 'Policy'}}}]}).encode())
    path = Path(path)
    binding = ExternalKnowledgeBinding(binding_id='domain-policy', provider='dify', endpoint='https://dify.example/v1',
        dataset_id='c42e2a6e-40b3-4330-96f8-f1e4d768e8c9', credential_ref=ProductionSecretHandle(
            protocol_id='local-environment-v1', handle_id='DOMAIN_TEST_KEY',
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL, version_id='env'))
    manifest = load_agent_manifest(path).model_copy(update={'knowledge_bindings': (binding,)})
    invocation = compose_harness_invocation(path, manifest=manifest, require_runtime_credentials=False,
        guarded_http_client=Http(), secret_provider=LocalEnvironmentSecretProvider(
            {'DOMAIN_TEST_KEY': 'synthetic-only'}, mode='development'))
    invocation = replace(invocation, intent_resolver=Intent())
    admitted = []
    orchestrator = build_controlled_react_orchestrator_for_invocation(invocation,
        business_flow_admission_callback=admitted.append)
    result = execute_agent_package_run(AgentPackageRunRequest(agent_yaml=path, manifest=manifest,
        run_id='domain-fixture', question=question, runs_dir=tmp_path / 'runs', controlled_react_orchestrator=orchestrator,
        guarded_http_client=Http(), secret_provider=LocalEnvironmentSecretProvider(
            {'DOMAIN_TEST_KEY': 'synthetic-only'}, mode='development')))
    assert admitted == [pack_id]
    assert question in queries
    assert result.workflow_template_execution_result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert fact in result.final_output
    assert result.workflow_template_execution_result.evidence
