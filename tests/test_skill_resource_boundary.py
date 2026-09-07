from pathlib import Path

import pytest

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.skills import load_business_flow_skill_pack_definition, load_business_flow_skill_pack_set
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


BASE = Path('proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3')
DEFINITION = 'schema_version: business_flow_skill_pack.v1\nid: service\nlabel: Service\ndescription: Service guidance\n'


def package(tmp_path: Path, *, reference: str = 'skill.yaml') -> Path:
    root = tmp_path / 'package'
    root.mkdir(exist_ok=True)
    (root / 'policy.yaml').write_text('rules: []\n')
    (root / 'skill.yaml').write_text(DEFINITION)
    text = (BASE / 'agent.yaml').read_text().replace('capabilities:\n', f'capabilities:\n  skills:\n    enabled: true\n    business_flows:\n      - id: service\n        definition: {reference}\n')
    path = root / 'agent.yaml'
    path.write_text(text)
    return path


def load(path: Path):
    return load_business_flow_skill_pack_set(load_agent_manifest(path), template=resolve_workflow_template('react_enterprise_qa_v3'), manifest_path=path)


@pytest.mark.parametrize('reference', ['../outside.yaml', '/tmp/outside.yaml', 'C:\\outside.yaml'])
def test_escaping_reference_rejected(tmp_path: Path, reference: str):
    with pytest.raises(ProofAgentError):
        load(package(tmp_path, reference=reference))


@pytest.mark.parametrize('kind', ['internal', 'external', 'parent'])
def test_all_skill_symlinks_rejected(tmp_path: Path, kind: str):
    path = package(tmp_path, reference='link.yaml' if kind != 'parent' else 'link/skill.yaml')
    target = path.parent / 'skill.yaml'
    if kind == 'external':
        target = tmp_path / 'outside.yaml'
        target.write_text(DEFINITION)
    if kind == 'parent':
        (path.parent / 'link').symlink_to(path.parent, target_is_directory=True)
    else:
        (path.parent / 'link.yaml').symlink_to(target)
    with pytest.raises(ProofAgentError):
        load(path)


@pytest.mark.parametrize('payload', [
    DEFINITION + 'description: replacement\n',
    DEFINITION + 'intent_patterns: &patterns [hello]\nintent_taxonomy_refs: *patterns\n',
    DEFINITION + '# padding\n' + ' ' * 65536,
    DEFINITION + 'intent_patterns: [' + '[' * 40 + 'x' + ']' * 40 + ']\n',
    b'\xff\xfe',
], ids=['duplicate-key', 'alias', 'oversize', 'depth', 'non-utf8'])
def test_unbounded_ambiguous_or_non_utf8_resources_rejected(tmp_path: Path, payload):
    path = tmp_path / 'skill.yaml'
    path.write_bytes(payload.encode() if isinstance(payload, str) else payload)
    with pytest.raises(ProofAgentError):
        load_business_flow_skill_pack_definition(path)


def test_schema_and_yaml_errors_do_not_echo_payload(tmp_path: Path):
    path = tmp_path / 'skill.yaml'
    for payload in [DEFINITION + 'admission: PRIVATE_PAYLOAD\n', DEFINITION + 'label: [PRIVATE_PAYLOAD\n']:
        path.write_text(payload)
        with pytest.raises(ProofAgentError) as error:
            load_business_flow_skill_pack_definition(path)
        import traceback
        assert 'PRIVATE_PAYLOAD' not in ''.join(traceback.format_exception(error.value))


def test_direct_set_loader_rejects_duplicate_and_excessive_bindings(tmp_path: Path):
    path = package(tmp_path)
    manifest = load_agent_manifest(path)
    binding = manifest.capabilities.skills.business_flows[0]
    for bindings in [(binding, binding), tuple(binding.model_copy(update={'id': f'service_{i}'}) for i in range(33))]:
        changed = manifest.model_copy(update={'capabilities': manifest.capabilities.model_copy(update={'skills': manifest.capabilities.skills.model_copy(update={'business_flows': bindings})})})
        with pytest.raises(ProofAgentError):
            load_business_flow_skill_pack_set(changed, template=resolve_workflow_template('react_enterprise_qa_v3'), manifest_path=path)


@pytest.mark.parametrize('field', ['knowledge_binding_refs', 'policy_rule_refs', 'validator_refs', 'tool_contract_refs'])
def test_unknown_capability_reference_rejected(tmp_path: Path, field: str):
    path = package(tmp_path)
    (path.parent / 'skill.yaml').write_text(DEFINITION + f'{field}: [PRIVATE_PAYLOAD]\n')
    with pytest.raises(ProofAgentError) as error:
        load(path)
    assert 'PRIVATE_PAYLOAD' not in str(error.value)


def test_loaded_definition_is_frozen_and_detached_from_resource(tmp_path: Path):
    path = package(tmp_path)
    (path.parent / 'skill.yaml').write_text(DEFINITION + 'stage_prompt_addenda:\n  plan:\n    business_context: original\n')
    packs = load(path)
    (path.parent / 'skill.yaml').write_text(DEFINITION)
    assert packs[0].stage_prompt_addenda['plan'].business_context == 'original'
    with pytest.raises((TypeError, ValueError)):
        packs[0].stage_prompt_addenda['plan'] = None
