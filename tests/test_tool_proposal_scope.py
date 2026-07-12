from __future__ import annotations

from proof_agent.capabilities.tools.gateway import ToolConfig
from proof_agent.contracts import (
    ControlledReActRunState,
    EffectiveToolProposalScope,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ToolProposalInterface,
    ToolProposalParameter,
    ToolProposalParameterSource,
)
from proof_agent.control.workflow.controlled_react import (
    ToolProposalParameterBinder,
    ToolProposalScopeResolver,
)
from proof_agent.errors import ProofAgentError


def test_effective_tool_proposal_scope_exposes_proposal_interface_only() -> None:
    resolver = ToolProposalScopeResolver()
    state = ControlledReActRunState(
        run_id="run_scope",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="Look up claim status.",
    )

    scope = resolver.resolve(
        state,
        tools={
            "claim_status_lookup": ToolConfig(
                name="claim_status_lookup",
                built_in_handler=None,
                tool_source_id="tool_mcp_claims",
                risk_level="medium",
                requires_approval=False,
                read_only=True,
                allowed_parameters=frozenset({"claim_id", "customer_id"}),
                denied_parameters=frozenset({"access_token"}),
                source="mcp",
                mcp_tool_name="claim.status.lookup",
                mcp_contract_snapshot={"digest": "sha256:contract"},
                input_schema={
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "description": "Claim id."},
                        "customer_id": {"type": "string"},
                        "access_token": {"type": "string"},
                    },
                    "required": ["claim_id", "customer_id"],
                },
                result_schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                },
                summary_fields=("status",),
                result_authority="authoritative_read",
            )
        },
    )

    assert scope.plan_round == 0
    assert scope.tool_contract_ids == ("claim_status_lookup",)
    assert scope.schema_digest.startswith("sha256:")
    interface = scope.tool_interfaces[0]
    assert interface.tool_contract_id == "claim_status_lookup"
    assert interface.source == "mcp"
    assert interface.mcp_tool_name is None
    assert interface.tool_source_id is None
    assert interface.input_schema == {}
    assert interface.result_schema == {}
    assert interface.semantic_result_summary == "Returns status."
    assert [parameter.name for parameter in interface.parameters] == [
        "claim_id",
        "customer_id",
    ]
    assert interface.parameters[0].required is True
    assert interface.parameters[0].value_source is ToolProposalParameterSource.USER_SUPPLIED


def test_tool_proposal_parameter_binder_injects_system_generated_parameters() -> None:
    state = ControlledReActRunState(
        run_id="run_bind",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="Create a ticket.",
    )
    scope = EffectiveToolProposalScope(
        run_id="run_bind",
        plan_round=0,
        schema_digest="sha256:scope",
        tool_interfaces=(
            ToolProposalInterface(
                tool_contract_id="create_service_ticket",
                purpose="create service ticket",
                risk_level="high",
                read_only=False,
                requires_approval=True,
                parameters=(
                    ToolProposalParameter(
                        name="ticket_subject",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.USER_SUPPLIED,
                    ),
                    ToolProposalParameter(
                        name="idempotency_key",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.SYSTEM_GENERATED,
                    ),
                ),
            ),
        ),
    )

    bound = ToolProposalParameterBinder().bind(
        state,
        _tool_action(
            tool_name="create_service_ticket",
            parameters={"ticket_subject": "Claim follow-up"},
        ),
        scope,
    )

    assert bound.tool_contract_id == "create_service_ticket"
    assert bound.parameters["ticket_subject"] == "Claim follow-up"
    assert bound.parameters["idempotency_key"] == ("run_bind:act_tool:create_service_ticket")
    assert bound.parameter_digest.startswith("sha256:")


def test_tool_proposal_parameter_binder_rejects_planner_supplied_system_parameter() -> None:
    state = ControlledReActRunState(
        run_id="run_bind",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="Create a ticket.",
    )
    scope = EffectiveToolProposalScope(
        run_id="run_bind",
        plan_round=0,
        schema_digest="sha256:scope",
        tool_interfaces=(
            ToolProposalInterface(
                tool_contract_id="create_service_ticket",
                purpose="create service ticket",
                risk_level="high",
                read_only=False,
                requires_approval=True,
                parameters=(
                    ToolProposalParameter(
                        name="idempotency_key",
                        required=True,
                        value_type="string",
                        value_source=ToolProposalParameterSource.SYSTEM_GENERATED,
                    ),
                ),
            ),
        ),
    )

    try:
        ToolProposalParameterBinder().bind(
            state,
            _tool_action(
                tool_name="create_service_ticket",
                parameters={"idempotency_key": "planner-generated"},
            ),
            scope,
        )
    except ProofAgentError as exc:
        assert exc.code == "PA_TOOL_PROPOSAL_001"
        assert "system-generated parameter" in exc.message
    else:
        raise AssertionError("planner-supplied system parameters must be rejected")


def _tool_action(
    *,
    tool_name: str,
    parameters: dict[str, object],
) -> ReActActionProposal:
    return ReActActionProposal(
        action_id="act_tool",
        action_type=ReActActionType.PROPOSE_TOOL_CALL,
        reasoning_summary=ReasoningSummary(
            goal="Use a governed tool.",
            observations=("The request needs a tool.",),
            candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
            selected_action=ReActActionType.PROPOSE_TOOL_CALL,
            rationale_summary="The tool proposal must be governed.",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters=parameters,
        target_tool_name=tool_name,
        risk_level="high",
    )
