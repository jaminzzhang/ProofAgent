from __future__ import annotations

from dataclasses import dataclass

from proof_agent.errors import ProofAgentError


@dataclass(frozen=True)
class WorkflowTemplate:
    """A registered governed workflow shape selected by an Agent Contract."""

    name: str
    description: str


TEMPLATES: dict[str, WorkflowTemplate] = {
    "enterprise_qa": WorkflowTemplate(
        name="enterprise_qa",
        description="Evidence-backed enterprise question answering.",
    ),
    "react_enterprise_qa": WorkflowTemplate(
        name="react_enterprise_qa",
        description="Controlled ReAct enterprise question answering.",
    ),
}


def resolve_workflow_template(name: str) -> WorkflowTemplate:
    """Resolve a workflow template name into its registered template metadata."""

    template = TEMPLATES.get(name)
    if template is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {name}",
            f"Supported workflow templates: {', '.join(sorted(TEMPLATES))}.",
        )
    return template
