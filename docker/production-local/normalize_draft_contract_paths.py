"""Normalize audit paths on one exact Draft through the existing CAS authority."""

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
_LEGACY_TRACE_PATH = "../../runs/latest/trace.jsonl"
_LEGACY_RECEIPT_PATH = "../../runs/latest/governance_receipt.md"
_NORMALIZED_TRACE_PATH = "./trace.jsonl"
_NORMALIZED_RECEIPT_PATH = "./governance_receipt.md"


class DraftContractPathNormalizationRejected(RuntimeError):
    """Stable refusal for the bounded production-local Draft mutation."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def normalize_draft_contract_paths(
    *,
    agent_id: str,
    draft_id: str,
    expected_revision: int,
    workspace: Any,
    actor: AuditActorFacts,
) -> dict[str, object]:
    """Normalize only the two known package-escaping Draft audit paths."""

    exact_agent_id = _exact_identifier(agent_id)
    exact_draft_id = _exact_identifier(draft_id)
    exact_revision = _exact_revision(expected_revision)
    current = workspace.get_draft(
        agent_id=exact_agent_id,
        draft_id=exact_draft_id,
    )
    if current.draft.agent_id != exact_agent_id or current.draft.draft_id != exact_draft_id:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_path_target_mismatch",
            detail="The Draft authority returned a different target.",
        )
    if current.revision != exact_revision:
        raise DraftContractPathNormalizationRejected(
            code="agent_draft_revision_conflict",
            detail="The exact Draft revision changed.",
        )

    candidate_yaml = _normalize_audit_paths(current.draft.contract_bundle.agent_yaml)
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
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_update_rejected",
            detail="The complete Draft Contract did not pass validation.",
        ) from exc

    if (
        saved.draft.agent_id != exact_agent_id
        or saved.draft.draft_id != exact_draft_id
        or saved.revision != exact_revision + 1
        or saved.draft.contract_bundle.agent_yaml != candidate_yaml
    ):
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_path_result_mismatch",
            detail="The Draft authority returned an unexpected saved result.",
        )
    trace_path, receipt_path = _audit_paths(candidate_yaml)
    if trace_path != _NORMALIZED_TRACE_PATH or receipt_path != _NORMALIZED_RECEIPT_PATH:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_path_result_mismatch",
            detail="The saved Draft audit paths did not match the command.",
        )

    return {
        "schema_version": "production-local-draft-contract-path-normalization.v1",
        "evidence_class": "local_production_validation_only",
        "status": "draft_updated",
        "publication_authorized": False,
        "agent_id": exact_agent_id,
        "draft_id": exact_draft_id,
        "previous_revision": exact_revision,
        "draft_revision": saved.revision,
        "trace_path": trace_path,
        "receipt_path": receipt_path,
    }


def main() -> None:
    values = os.environ
    agent_id = _required(values, "PROOF_AGENT_DRAFT_PATH_AGENT_ID")
    draft_id = _required(values, "PROOF_AGENT_DRAFT_PATH_DRAFT_ID")
    expected_revision = _environment_revision(
        _required(values, "PROOF_AGENT_DRAFT_PATH_EXPECTED_REVISION")
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
        _compose_and_normalize(
            values=values,
            agent_id=agent_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
            actor=actor,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


async def _compose_and_normalize(
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
        return normalize_draft_contract_paths(
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
    except DraftContractPathNormalizationRejected as error:
        error_code = _failure_code(error.code)
    except (AgentConfigurationConflict, AgentConfigurationNotFound) as error:
        error_code = _failure_code(error.code)
    except ProofAgentError as error:
        error_code = _failure_code(error.code)
    except ValueError:
        error_code = "invalid_draft_contract_path_normalization_input"
    except Exception:
        error_code = "production_local_draft_contract_path_normalization_failed"
    else:
        return 0

    print(
        json.dumps(
            {
                "schema_version": ("production-local-draft-contract-path-normalization-failure.v1"),
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


def _normalize_audit_paths(agent_yaml: str) -> str:
    try:
        root = yaml.compose(agent_yaml)
        before = yaml.safe_load(agent_yaml)
        trace_node = _mapping_path(root, ("audit", "trace_path"))
        receipt_node = _mapping_path(root, ("audit", "receipt_path"))
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail="The Draft audit path contract is invalid or ambiguous.",
        ) from exc
    if not isinstance(before, dict):
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail="The Draft Contract must be a mapping.",
        )

    trace_path = str(trace_node.value)
    receipt_path = str(receipt_node.value)
    if trace_path == _NORMALIZED_TRACE_PATH and receipt_path == _NORMALIZED_RECEIPT_PATH:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_already_normalized",
            detail="The Draft audit paths are already normalized; no new revision is allowed.",
        )
    if trace_path != _LEGACY_TRACE_PATH or receipt_path != _LEGACY_RECEIPT_PATH:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail="The Draft audit paths do not match the exact legacy contract.",
        )

    candidate = agent_yaml
    edits = (
        (trace_node.start_mark.index, trace_node.end_mark.index, _NORMALIZED_TRACE_PATH),
        (
            receipt_node.start_mark.index,
            receipt_node.end_mark.index,
            _NORMALIZED_RECEIPT_PATH,
        ),
    )
    for start, end, replacement in sorted(edits, reverse=True):
        candidate = candidate[:start] + replacement + candidate[end:]
    try:
        after = yaml.safe_load(candidate)
        expected = deepcopy(before)
        expected["audit"]["trace_path"] = _NORMALIZED_TRACE_PATH
        expected["audit"]["receipt_path"] = _NORMALIZED_RECEIPT_PATH
    except (KeyError, TypeError, yaml.YAMLError) as exc:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail="The Draft audit paths cannot be changed safely.",
        ) from exc
    if after != expected:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail="The Draft mutation changed more than the two audit paths.",
        )
    return candidate


def _audit_paths(agent_yaml: str) -> tuple[str, str]:
    try:
        root = yaml.compose(agent_yaml)
        trace_path = str(_mapping_path(root, ("audit", "trace_path")).value)
        receipt_path = str(_mapping_path(root, ("audit", "receipt_path")).value)
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        raise DraftContractPathNormalizationRejected(
            code="draft_contract_path_result_mismatch",
            detail="The saved Draft audit path contract is invalid.",
        ) from exc
    return trace_path, receipt_path


def _mapping_path(root: Node | None, path: tuple[str, ...]) -> ScalarNode:
    current = root
    for index, segment in enumerate(path):
        if not isinstance(current, MappingNode):
            raise TypeError("audit path is not a mapping")
        _, current = _mapping_entry(current, segment)
        if index < len(path) - 1 and not isinstance(current, MappingNode):
            raise TypeError("audit path is not a mapping")
    if not isinstance(current, ScalarNode):
        raise TypeError("audit path value is not a scalar")
    return current


def _mapping_entry(mapping: MappingNode, name: str) -> tuple[ScalarNode, Node]:
    matches = [
        (key, value)
        for key, value in mapping.value
        if isinstance(key, ScalarNode) and key.value == name
    ]
    if len(matches) != 1:
        raise ValueError("audit path is missing or duplicated")
    return matches[0]


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
        return "production_local_draft_contract_path_normalization_failed"
    return normalized


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(cli())
