from fastapi.testclient import TestClient
from proof_agent.observability.api.app import create_app


def test_validate_explains_missing_server_egress_policy(tmp_path, monkeypatch):
    monkeypatch.setenv('PROOF_AGENT_MODE', 'development')
    monkeypatch.delenv('PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY', raising=False)
    client = TestClient(create_app(history_dir=tmp_path/'history', runs_dir=tmp_path/'runs',
        conversations_dir=tmp_path/'conversations', agent_configuration_dir=tmp_path/'config'))
    draft = client.post('/api/config/agents/import', json={'manifest_path': 'proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml'}).json()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}"
    revision = client.get(base+'/external-knowledge').json()['revision']
    saved = client.patch(base+'/external-knowledge', json={'expected_revision': revision, 'bindings': [{
        'binding_id': 'manuals', 'provider': 'agentset', 'endpoint': 'https://api.agentset.ai/v1', 'namespace_id': 'ns_manuals',
        'credential_ref': {'protocol_id': 'local-environment-v1', 'handle_id': 'SYNTHETIC_KEY', 'purpose': 'knowledge_credential', 'version_id': 'env'},
    }]})
    assert saved.status_code == 200
    response = client.post(base+'/validate', json={'question': 'What is the limit?'})
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'PA_CONFIG_002'
    assert 'PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY' in response.json()['detail']['fix'], response.text


def test_explicit_development_policy_composes_both_dependencies(tmp_path, monkeypatch):
    import json
    from proof_agent.bootstrap.external_knowledge import development_knowledge_dependencies
    from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
    from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
    policy = tmp_path / 'egress.json'
    policy.write_text(json.dumps({'version_id': 'test', 'revision': 1, 'created_at': '2026-09-07T00:00:00Z',
        'created_by': 'test', 'rules': [{'origin': {'host': 'api.agentset.ai', 'port': 443}, 'allowed_ip_networks': ['203.0.113.8/32']}]}))
    monkeypatch.setenv('PROOF_AGENT_MODE', 'development')
    monkeypatch.setenv('PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY', str(policy))
    http, secrets = development_knowledge_dependencies(None, None)
    assert isinstance(http, GuardedHttpsClient)
    assert isinstance(secrets, LocalEnvironmentSecretProvider)
