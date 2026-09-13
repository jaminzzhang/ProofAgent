import pytest
from proof_agent.contracts.workflow_policy import InteractionPolicy
from proof_agent.control.workflow.interaction import decide_interaction


@pytest.mark.parametrize('stage', ['goal', 'plan', 'evidence', 'tool_input', 'finalization'])
def test_required_context_cannot_be_defaulted_at_any_checkpoint(stage):
    result = decide_interaction(InteractionPolicy(mode='autonomous', intensity='minimal'),
                                stage=stage, reason='required_context', has_default=True)
    assert result == 'missing_context'


def test_optional_preferences_can_be_automated_without_changing_required_fields():
    policy = InteractionPolicy(intensity='balanced')
    assert decide_interaction(policy, stage='goal', reason='preference', has_default=True) == 'continue'
    assert decide_interaction(policy, stage='goal', reason='required_context', has_default=True) == 'ask'


def test_checkpoint_override_and_round_limit_apply_together():
    policy = InteractionPolicy(intensity='minimal', max_rounds=1,
                               checkpoints={'plan': {'intensity': 'thorough'}})
    assert decide_interaction(policy, stage='goal', reason='preference') == 'continue'
    assert decide_interaction(policy, stage='plan', reason='preference') == 'ask'
    assert decide_interaction(policy, stage='plan', reason='preference', rounds_asked=1) == 'continue'
    assert decide_interaction(policy, stage='plan', reason='required_context', rounds_asked=1) == 'missing_context'


def test_no_channel_pause_never_counts_as_an_answer():
    policy = InteractionPolicy(mode='autonomous', unavailable='pause')
    assert decide_interaction(policy, stage='tool_input', reason='required_parameter') == 'pause'


def test_retrievable_facts_are_retrieved_even_when_questions_are_thorough():
    assert decide_interaction(InteractionPolicy(mode='interactive', intensity='thorough'),
                               stage='evidence', reason='retrievable') == 'continue'
