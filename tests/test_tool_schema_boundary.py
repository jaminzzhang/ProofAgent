import pytest

from proof_agent.capabilities.tools.gateway import ToolConfig, ToolGateway
from proof_agent.errors import ProofAgentError


def test_nested_tool_input_is_rejected_before_transport():
    config = ToolConfig(name='calc', built_in_handler=None, source='mcp', tool_source_id='source', mcp_tool_name='calc',
        risk_level='low', requires_approval=False, read_only=True, allowed_parameters=frozenset({'values'}),
        denied_parameters=frozenset(), input_schema={'type': 'object', 'required': ['values'],
            'properties': {'values': {'type': 'array', 'items': {'type': 'string', 'pattern': r'^\d+\.\d+$'}}}},
        result_schema={'type': 'object'}, mcp_contract_snapshot={'digest': 'sha256:fixture'}, summary_fields=('total',),
        result_authority='authoritative_read')
    with pytest.raises(ProofAgentError, match='input_schema'):
        ToolGateway({'calc': config}).request_tool(tool_name='calc', parameters={'values': [0.1]}, approved=True)


@pytest.mark.parametrize('schema,value', [
    ({'type': 'object', 'properties': {'nested': {'type': 'object', 'required': ['count'], 'properties': {'count': {'type': 'integer'}}}}}, {'nested': {'count': True}}),
    ({'type': 'array', 'items': {'type': 'string'}, 'maxItems': 2}, ['a', 'b', 'c']),
    ({'type': 'object', 'additionalProperties': False}, {'extra': 'value'}),
    ({'type': 'string', 'enum': ['open', 'closed']}, 'OPEN'),
    ({'type': 'number'}, float('nan')),
    ({'$ref': 'https://example.test/private-schema'}, {}),
    ({'$ref': '#/missing'}, {}),
    ({'type': 'unknown_type'}, {}),
])
def test_recursive_schema_failure_is_closed_and_sanitized(schema, value):
    from proof_agent.capabilities.tools.schema import validate_tool_schema
    with pytest.raises(ProofAgentError) as error:
        validate_tool_schema(schema, value, label='result_schema')
    assert error.value.code == 'PA_TOOL_SOURCE_002'
    assert 'private-schema' not in str(error.value)


def test_local_schema_reference_accepts_valid_nested_values():
    from proof_agent.capabilities.tools.schema import validate_tool_schema
    validate_tool_schema({'$defs': {'amount': {'type': 'string', 'pattern': r'^\d+\.\d+$'}},
        'type': 'array', 'items': {'$ref': '#/$defs/amount'}}, ('0.1', '0.2'), label='input_schema')
