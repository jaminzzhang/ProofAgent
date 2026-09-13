"""Agent configuration must control execution, rather than silently ignore policy."""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from proof_agent.bootstrap.manifest import manifest_from_mapping

AGENT = Path('proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml')


def load_policy(**overrides):
    raw = yaml.safe_load(AGENT.read_text())
    raw.update(overrides)
    return manifest_from_mapping(raw, base_dir=AGENT.parent.resolve())


def test_execution_configuration_survives_agent_loading():
    raw = yaml.safe_load(AGENT.read_text())
    raw['workflow']['execution'] = {'complexity': 'lite', 'ceiling': 'deep'}
    raw['interaction'] = {'mode': 'adaptive', 'intensity': 'minimal', 'max_rounds': 2}
    raw['assurance'] = {'level': 'strict'}
    manifest = manifest_from_mapping(raw, base_dir=AGENT.parent.resolve())
    assert manifest.workflow.execution.complexity == 'lite'
    assert manifest.interaction.intensity == 'minimal'
    assert manifest.assurance.level == 'strict'


@pytest.mark.parametrize('field,value', [
    ('interaction', {'mode': 'adaptive', 'allow_missing_identity': True}),
    ('assurance', {'level': 'strict', 'confidence': .95}),
])
def test_unsupported_policy_fields_are_rejected(field, value):
    with pytest.raises(ValidationError):
        load_policy(**{field: value})


def test_conflicting_legacy_and_new_clarification_levels_fail_explicitly():
    with pytest.raises(ValidationError):
        load_policy(response={'clarification_level': 'thorough'},
                    interaction={'intensity': 'minimal'})


def test_legacy_agent_does_not_implicitly_change_execution():
    manifest = load_policy()
    assert manifest.workflow.execution is None
    assert manifest.interaction is None
    assert manifest.assurance is None
