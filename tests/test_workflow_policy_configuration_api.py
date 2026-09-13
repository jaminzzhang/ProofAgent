"""Workflow policy commands through both route families and real test persistence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from proof_agent.contracts import AuditActorFacts
from proof_agent.delivery.agent_configuration_workflow_stages import LocalAgentConfigurationWorkflowStageAdapter
from proof_agent.delivery.production_agent_configuration import router as production_router
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import LocalOperatorIdentityProvider, OperatorIdentityContext, OperatorPermission


@pytest.fixture(params=['development', 'production'])
def configured_client(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[TestClient, str, Any]:
    application = create_app(
        history_dir=tmp_path / 'history', runs_dir=tmp_path / 'latest',
        conversations_dir=tmp_path / 'conversations', published_agents={},
        agent_configuration_dir=tmp_path / 'config',
    )
    imported = TestClient(application).post('/api/config/agents/import', json={
        'manifest_path': 'proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml',
    })
    assert imported.status_code == 200, imported.text
    draft = imported.json()
    workspace = application.state.agent_configuration_workspace
    route = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}"
    if request.param == 'production':
        application = FastAPI()
        application.state.agent_configuration_workspace = workspace
        application.state.proof_agent_mode = 'development'
        application.include_router(production_router, prefix='/api')
    application.dependency_overrides[get_operator_identity] = LocalOperatorIdentityProvider().current_identity
    return TestClient(application), route, workspace


def _record(client: TestClient, route: str) -> dict[str, Any]:
    response = client.get(route)
    assert response.status_code == 200, response.text
    return response.json()


def test_atomic_policy_and_stage_round_trip_preserves_absent_and_explicitly_removes(
    configured_client: tuple[TestClient, str, Any],
) -> None:
    client, route, _ = configured_client
    initial = _record(client, route)
    policy = {
        'execution': {'complexity': 'lite', 'ceiling': 'deep'},
        'interaction': {'mode': 'adaptive', 'intensity': 'thorough', 'checkpoints': {'finalization': {'ask_on': ['applicability_unresolved']}}},
        'assurance': {'level': 'strict', 'evidence': {'min_sources': 2}},
    }
    response = client.patch(f'{route}/workflow-stages', json={
        'expected_revision': initial['revision'], 'stages': [{'id': 'plan', 'prompt': {'business_context': 'Review requested scope.'}}], 'policy': policy,
    })
    assert response.status_code == 200, response.text
    raw = yaml.safe_load(response.json()['agent_yaml'])
    assert raw['workflow']['execution'] == policy['execution']
    assert raw['interaction'] == policy['interaction']
    assert raw['assurance'] == policy['assurance']
    assert raw['workflow']['stages'][0]['prompt']['business_context'] == 'Review requested scope.'
    saved = _record(client, route)
    assert saved['revision'] == initial['revision'] + 1
    assert len(saved['operation_audit']) == len(initial['operation_audit']) + 1
    response = client.patch(f'{route}/workflow-stages', json={
        'expected_revision': saved['revision'], 'stages': [], 'policy': {'interaction': None},
    })
    assert response.status_code == 200, response.text
    raw = yaml.safe_load(response.json()['agent_yaml'])
    assert 'interaction' not in raw
    assert raw['workflow']['execution'] == policy['execution']
    assert raw['assurance'] == policy['assurance']
    stale = client.patch(f'{route}/workflow-stages', json={
        'expected_revision': saved['revision'], 'stages': [], 'policy': {'execution': {'complexity': 'deep'}},
    })
    assert stale.status_code == 409
    assert stale.json()['detail'] == 'agent_draft_revision_conflict'


def test_execution_preview_is_revision_bound_read_only_and_uses_the_backend_compiler(
    configured_client: tuple[TestClient, str, Any],
) -> None:
    client, route, _ = configured_client
    initial = _record(client, route)
    legacy = client.post(f'{route}/workflow-execution/preview', json={'expected_revision': initial['revision'], 'policy': {}})
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()['effective_complexity'] == 'legacy'
    assert legacy.json()['budget'] is None
    preview = client.post(f'{route}/workflow-execution/preview', json={
        'expected_revision': initial['revision'], 'policy': {'execution': {'complexity': 'lite'}, 'assurance': {'level': 'strict'}},
    })
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan['effective_complexity'] == 'lite'
    assert len(plan['configuration_digest']) == 64
    assert len(plan['stages']) == 10
    by_stage = {stage['stage_id']: stage for stage in plan['stages']}
    assert by_stage['plan']['mode'] == 'deterministic'
    assert by_stage['memory']['mode'] == 'bypass'
    assert 'goal_acceptance' in by_stage['response']['mandatory_checks']
    assert _record(client, route) == initial
    stale = client.post(f'{route}/workflow-execution/preview', json={'expected_revision': initial['revision'] + 1, 'policy': {}})
    assert stale.status_code == 409
    assert client.post(f'{route}/workflow-execution/preview', json={'policy': {}}).status_code == 422


@pytest.mark.parametrize('policy', [
    {'unknown': {}}, {'execution': {'skip_validation': True}},
    {'execution': {'budget': {'max_model_calls': True}}},
    {'execution': {'complexity': 'deep', 'ceiling': 'lite'}},
    {'interaction': {'checkpoints': {'unknown': {'intensity': 'thorough'}}}},
])
def test_invalid_policy_is_rejected_before_any_state_change(
    configured_client: tuple[TestClient, str, Any], policy: dict[str, Any],
) -> None:
    client, route, _ = configured_client
    initial = _record(client, route)
    payload = {'expected_revision': initial['revision'], 'policy': policy}
    assert client.post(f'{route}/workflow-execution/preview', json=payload).status_code == 422
    assert client.patch(f'{route}/workflow-stages', json={**payload, 'stages': []}).status_code == 422
    assert _record(client, route) == initial


def test_whole_manifest_clarification_conflict_blocks_save_and_preview(
    configured_client: tuple[TestClient, str, Any],
) -> None:
    client, route, _ = configured_client
    initial = _record(client, route)
    contract = client.get(f'{route}/contract').json()
    raw = yaml.safe_load(contract['agent_yaml'])
    raw['response']['clarification_level'] = 'minimal'
    configured = client.patch(f'{route}/contract', json={'expected_revision': initial['revision'], 'agent_yaml': yaml.safe_dump(raw)})
    assert configured.status_code == 200, configured.text
    before = _record(client, route)
    payload = {'expected_revision': before['revision'], 'policy': {'interaction': {'intensity': 'thorough'}}}
    for response in (
        client.post(f'{route}/workflow-execution/preview', json=payload),
        client.patch(f'{route}/workflow-stages', json={**payload, 'stages': []}),
    ):
        assert response.status_code == 400, response.text
    assert _record(client, route) == before


@pytest.mark.parametrize('operation', ['save', 'preview'])
def test_policy_commands_require_the_corresponding_operator_permission(
    configured_client: tuple[TestClient, str, Any], operation: str,
) -> None:
    client, route, _ = configured_client
    client.app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id='viewer', display_name='Viewer', permissions=frozenset({OperatorPermission.AGENT_VIEW}),
    )
    response = (client.patch(f'{route}/workflow-stages', json={'expected_revision': 1, 'stages': [], 'policy': {}})
        if operation == 'save' else client.post(f'{route}/workflow-execution/preview', json={'expected_revision': 1, 'policy': {}}))
    assert response.status_code == 403


@pytest.mark.parametrize('operation', ['save', 'preview'])
def test_concurrent_revision_change_during_inspection_fences_policy_save_and_preview(
    configured_client: tuple[TestClient, str, Any], monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    client, route, workspace = configured_client
    initial = _record(client, route)
    inspect = LocalAgentConfigurationWorkflowStageAdapter.inspect

    def race(self: LocalAgentConfigurationWorkflowStageAdapter, *, draft: Any) -> Any:
        facts = inspect(self, draft=draft)
        workspace.update_draft(
            agent_id=draft.agent_id, draft_id=draft.draft_id,
            expected_revision=initial['revision'], display_name=None,
            purpose='Concurrent writer won.', actor=AuditActorFacts(subject='other-operator', identity_provider='local-test', session_id='test-session'),
        )
        return facts

    monkeypatch.setattr(LocalAgentConfigurationWorkflowStageAdapter, 'inspect', race)
    payload = {'expected_revision': initial['revision'], 'policy': {'execution': {'complexity': 'lite'}}}
    response = (client.patch(f'{route}/workflow-stages', json={**payload, 'stages': []})
        if operation == 'save' else client.post(f'{route}/workflow-execution/preview', json=payload))
    assert response.status_code == 409, response.text
    winner = _record(client, route)
    assert winner['purpose'] == 'Concurrent writer won.'
    assert winner['revision'] == initial['revision'] + 1
    assert 'execution' not in yaml.safe_load(client.get(f'{route}/contract').json()['agent_yaml'])['workflow']
