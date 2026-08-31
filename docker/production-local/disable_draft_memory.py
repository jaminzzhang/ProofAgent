"""Disable Memory on one exact production-local Draft through the existing CAS authority."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

import yaml  # type: ignore[import-untyped]
from yaml.nodes import MappingNode, Node, ScalarNode  # type: ignore[import-untyped]

from proof_agent.contracts import AuditActorFacts, Permission
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationConflict,
    AgentConfigurationNotFound,
)
from proof_agent.errors import ProofAgentError


_EXACT_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_BOOLEAN_TAG = "tag:yaml.org,2002:bool"


class DraftMemoryDisableRejected(RuntimeError):
    """Stable refusal for the bounded production-local Draft mutation."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def disable_draft_memory(
    *,
    agent_id: str,
    draft_id: str,
    expected_revision: int,
    workspace: Any,
    actor: AuditActorFacts,
) -> dict[str, object]:
    """Normalize one exact Draft's Memory mapping from enabled to disabled."""

    exact_agent_id = _exact_identifier(agent_id)
    exact_draft_id = _exact_identifier(draft_id)
    exact_revision = _exact_revision(expected_revision)
    current = workspace.get_draft(
        agent_id=exact_agent_id,
        draft_id=exact_draft_id,
    )
    if current.draft.agent_id != exact_agent_id or current.draft.draft_id != exact_draft_id:
        raise DraftMemoryDisableRejected(
            code="draft_memory_disable_target_mismatch",
            detail="The Draft authority returned a different target.",
        )
    if current.revision != exact_revision:
        raise DraftMemoryDisableRejected(
            code="agent_draft_revision_conflict",
            detail="The exact Draft revision changed.",
        )

    candidate_yaml = _normalize_memory_mapping(current.draft.contract_bundle.agent_yaml)
    try:
        saved = workspace.update_contract(
            agent_id=exact_agent_id,
            draft_id=exact_draft_id,
            expected_revision=exact_revision,
            agent_yaml=candidate_yaml,
            policy_yaml=None,
            tools_yaml=None,
            actor=actor,
        )
    except (KeyError, ValueError, ProofAgentError) as exc:
        raise DraftMemoryDisableRejected(
            code="draft_contract_update_rejected",
            detail="The complete Draft Contract did not pass validation.",
        ) from exc

    if (
        saved.draft.agent_id != exact_agent_id
        or saved.draft.draft_id != exact_draft_id
        or saved.revision != exact_revision + 1
        or saved.draft.contract_bundle.agent_yaml != candidate_yaml
    ):
        raise DraftMemoryDisableRejected(
            code="draft_memory_disable_result_mismatch",
            detail="The Draft authority returned an unexpected saved result.",
        )
    tools_enabled, memory_enabled = _capability_states(candidate_yaml)
    if tools_enabled or memory_enabled:
        raise DraftMemoryDisableRejected(
            code="draft_memory_disable_result_mismatch",
            detail="The saved Draft capability state did not match the command.",
        )

    return {
        "schema_version": "production-local-draft-memory-disable.v1",
        "evidence_class": "local_production_validation_only",
        "status": "draft_updated",
        "publication_authorized": False,
        "agent_id": exact_agent_id,
        "draft_id": exact_draft_id,
        "previous_revision": exact_revision,
        "draft_revision": saved.revision,
        "tools_enabled": tools_enabled,
        "memory_enabled": memory_enabled,
    }


def main() -> None:
    values = os.environ
    agent_id = _required(values, "PROOF_AGENT_DRAFT_MEMORY_AGENT_ID")
    draft_id = _required(values, "PROOF_AGENT_DRAFT_MEMORY_DRAFT_ID")
    expected_revision = _environment_revision(
        _required(values, "PROOF_AGENT_DRAFT_MEMORY_EXPECTED_REVISION")
    )
    actor = AuditActorFacts(
        subject=_required(values, "PROOF_AGENT_RELEASE_ACTOR_SUBJECT"),
        identity_provider=_required(
            values,
            "PROOF_AGENT_RELEASE_ACTOR_IDENTITY_PROVIDER",
        ),
        session_id=_required(values, "PROOF_AGENT_RELEASE_ACTOR_SESSION_ID"),
        permissions=(Permission.AGENT_EDIT.value,),
    )
    result = asyncio.run(
        _compose_and_disable(
            values=values,
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            actor=actor,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


async def _compose_and_disable(
    *,
    values: Mapping[str, str],
    agent_id: str,
    draft_id: str,
    expected_revision: int,
    actor: AuditActorFacts,
) -> dict[str, object]:
    import warnings

    from authlib.deprecate import (  # type: ignore[import-untyped]
        AuthlibDeprecationWarning,
    )

    warnings.simplefilter("ignore", AuthlibDeprecationWarning)
    from proof_agent.bootstrap.production_roles import create_production_api_application

    application = create_production_api_application(environment=values)
    async with application.router.lifespan_context(application):
        workspace = application.state.agent_configuration_workspace
        if workspace is None:
            raise RuntimeError("Agent Configuration Workspace is unavailable")
        return disable_draft_memory(
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            workspace=workspace,
            actor=actor,
        )


def cli() -> int:
    """Run the exact CAS command with bounded, secret-free failure output."""

    try:
        main()
    except DraftMemoryDisableRejected as error:
        error_code = _failure_code(error.code)
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as error:
        error_code = _failure_code(error.code)
    except ProofAgentError as error:
        error_code = _failure_code(error.code)
    except ValueError:
        error_code = "invalid_draft_memory_disable_input"
    except Exception:
        error_code = "production_local_draft_memory_disable_failed"
    else:
        return 0

    print(
        json.dumps(
            {
                "schema_version": "production-local-draft-memory-disable-failure.v1",
                "status": "failed",
                "error_code": error_code,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )
    return 1


def _normalize_memory_mapping(agent_yaml: str) -> str:
    try:
        root = yaml.compose(agent_yaml)
        before = yaml.safe_load(agent_yaml)
        tools_node = _mapping_path(root, ("capabilities", "tools", "enabled"))
        memory_node = _mapping_path(root, ("capabilities", "memory", "enabled"))
        memory_mapping = _mapping_node(root, ("capabilities", "memory"))
        tools_enabled = _strict_boolean(tools_node)
        memory_enabled = _strict_boolean(memory_node)
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise DraftMemoryDisableRejected(
            code="draft_memory_contract_invalid",
            detail="The Draft capability contract is invalid or ambiguous.",
        ) from exc

    if tools_enabled:
        raise DraftMemoryDisableRejected(
            code="draft_tools_must_be_disabled",
            detail="Tools must remain disabled for the initial production candidate.",
        )
    if not memory_enabled:
        raise DraftMemoryDisableRejected(
            code="draft_memory_already_disabled",
            detail="Memory is already disabled; no new revision is allowed.",
        )
    try:
        if _mapping_entry_count(memory_mapping, "scopes") != 0:
            raise ValueError("memory scopes require a separate explicit repair")
        provider_key, provider_node = _mapping_entry(memory_mapping, "provider")
        if not isinstance(provider_node, ScalarNode):
            raise TypeError("memory provider is not a scalar")
        provider_start, provider_end = _single_line_entry_span(
            agent_yaml,
            key=provider_key,
            value=provider_node,
        )
    except (TypeError, ValueError) as exc:
        raise DraftMemoryDisableRejected(
            code="draft_memory_contract_invalid",
            detail="The enabled Memory capability cannot be normalized safely.",
        ) from exc
    if not isinstance(before, dict):
        raise DraftMemoryDisableRejected(
            code="draft_memory_contract_invalid",
            detail="The Draft capability contract must be a mapping.",
        )

    candidate = agent_yaml
    edits = (
        (memory_node.start_mark.index, memory_node.end_mark.index, "false"),
        (provider_start, provider_end, ""),
    )
    for start, end, replacement in sorted(edits, reverse=True):
        candidate = candidate[:start] + replacement + candidate[end:]
    try:
        after = yaml.safe_load(candidate)
        expected = deepcopy(before)
        expected["capabilities"]["memory"]["enabled"] = False
        del expected["capabilities"]["memory"]["provider"]
    except (KeyError, TypeError, yaml.YAMLError) as exc:
        raise DraftMemoryDisableRejected(
            code="draft_memory_contract_invalid",
            detail="The Draft capability contract cannot be changed safely.",
        ) from exc
    if after != expected:
        raise DraftMemoryDisableRejected(
            code="draft_memory_contract_invalid",
            detail="The Draft mutation changed more than the Memory capability.",
        )
    return candidate


def _capability_states(agent_yaml: str) -> tuple[bool, bool]:
    try:
        root = yaml.compose(agent_yaml)
        tools = _strict_boolean(_mapping_path(root, ("capabilities", "tools", "enabled")))
        memory = _strict_boolean(_mapping_path(root, ("capabilities", "memory", "enabled")))
        memory_mapping = _mapping_node(root, ("capabilities", "memory"))
        if (
            _mapping_entry_count(memory_mapping, "provider") != 0
            or _mapping_entry_count(memory_mapping, "scopes") != 0
        ):
            raise ValueError("disabled memory retained active configuration")
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise DraftMemoryDisableRejected(
            code="draft_memory_disable_result_mismatch",
            detail="The saved Draft capability state is invalid.",
        ) from exc
    return tools, memory


def _mapping_path(root: Node | None, path: tuple[str, ...]) -> ScalarNode:
    current = _mapping_value(root, path)
    if not isinstance(current, ScalarNode):
        raise TypeError("capability value is not a scalar")
    return current


def _mapping_node(root: Node | None, path: tuple[str, ...]) -> MappingNode:
    current = _mapping_value(root, path)
    if not isinstance(current, MappingNode):
        raise TypeError("capability value is not a mapping")
    return current


def _mapping_value(root: Node | None, path: tuple[str, ...]) -> Node:
    current = root
    for index, segment in enumerate(path):
        if not isinstance(current, MappingNode):
            raise TypeError("capability path is not a mapping")
        _, current = _mapping_entry(current, segment)
        if index < len(path) - 1 and not isinstance(current, MappingNode):
            raise TypeError("capability path is not a mapping")
    return current


def _mapping_entry(mapping: MappingNode, name: str) -> tuple[ScalarNode, Node]:
    matches = [
        (key, value)
        for key, value in mapping.value
        if isinstance(key, ScalarNode) and key.value == name
    ]
    if len(matches) != 1:
        raise ValueError("capability path is missing or duplicated")
    return matches[0]


def _mapping_entry_count(mapping: MappingNode, name: str) -> int:
    return sum(1 for key, _ in mapping.value if isinstance(key, ScalarNode) and key.value == name)


def _single_line_entry_span(
    document: str,
    *,
    key: ScalarNode,
    value: ScalarNode,
) -> tuple[int, int]:
    if key.start_mark.line != value.end_mark.line:
        raise ValueError("memory provider must use one block-mapping line")
    line_start = document.rfind("\n", 0, key.start_mark.index) + 1
    newline = document.find("\n", value.end_mark.index)
    line_end = len(document) if newline == -1 else newline + 1
    if document[line_start : key.start_mark.index].strip():
        raise ValueError("memory provider must use a block-mapping line")
    suffix_end = len(document) if newline == -1 else newline
    suffix = document[value.end_mark.index : suffix_end].strip()
    if suffix and not suffix.startswith("#"):
        raise ValueError("memory provider line has unsupported trailing content")
    return line_start, line_end


def _strict_boolean(node: ScalarNode) -> bool:
    value = str(node.value)
    if node.tag != _BOOLEAN_TAG or value not in {"true", "false"}:
        raise ValueError("capability value is not a strict boolean")
    return value == "true"


def _exact_identifier(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        raise ValueError("exact Draft identifier is invalid")
    return normalized


def _exact_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected Draft revision is invalid")
    return value


def _environment_revision(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("expected Draft revision is invalid")
    return _exact_revision(int(value))


def _failure_code(value: str) -> str:
    normalized = value.strip()
    if not _EXACT_IDENTIFIER.fullmatch(normalized):
        return "production_local_draft_memory_disable_failed"
    return normalized


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(cli())
