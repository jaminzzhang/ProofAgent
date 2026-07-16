from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts.agent_configuration import PublishedAgentVersion
from proof_agent.contracts.ports.agent_lifecycle import AgentLifecycleRepository
from proof_agent.contracts.ports.security_configuration import SecurityConfigurationRepository
from proof_agent.contracts.run_execution import RunExecutionSnapshot, RunRequest
from proof_agent.contracts.shared_assets import SharedAssetKind


class RunSnapshotAuthorityError(RuntimeError):
    """An exact publication/security dependency cannot be frozen for execution."""


class RunExecutionSnapshotAuthority:
    """Freeze the exact immutable configuration authority before any provider call."""

    def __init__(
        self,
        *,
        agents: AgentLifecycleRepository,
        security: SecurityConfigurationRepository,
        release_id: str,
        image_digest: str,
    ) -> None:
        normalized_image = image_digest.removeprefix("sha256:")
        if len(normalized_image) != 64 or any(
            char not in "0123456789abcdef" for char in normalized_image
        ):
            raise ValueError("Run Executor image digest must be an exact SHA-256")
        if not release_id or len(release_id) > 128:
            raise ValueError("Run Executor release id is invalid")
        self._agents = agents
        self._security = security
        self._release_id = release_id
        self._image_digest = normalized_image

    def __call__(
        self,
        request: RunRequest,
        attempt_id: str,
        attempt_number: int,
        frozen_at: datetime,
    ) -> RunExecutionSnapshot:
        version = self._agents.get_published(request.agent_id, request.agent_version_id)
        if version is None or version.version_id != request.agent_version_id:
            raise RunSnapshotAuthorityError("Published Agent Version is unavailable")
        permission_mapping = self._security.get_permission_mapping(
            request.permission_mapping_version_id
        )
        if permission_mapping is None:
            raise RunSnapshotAuthorityError("Permission Mapping Version is unavailable")
        egress_policy = self._security.get_active_egress_policy()
        if egress_policy is None:
            raise RunSnapshotAuthorityError("Active Egress Policy is unavailable")
        return RunExecutionSnapshot(
            run_id=request.run_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            release_id=self._release_id,
            image_digest=self._image_digest,
            agent_id=request.agent_id,
            agent_version_id=request.agent_version_id,
            agent_configuration_sha256=_sha(version.model_dump(mode="json")),
            knowledge_configuration_sha256=_sha(
                {
                    "bindings": (
                        None
                        if version.resolved_knowledge_bindings is None
                        else version.resolved_knowledge_bindings.model_dump(mode="json")
                    ),
                    "assets": _asset_refs(version, SharedAssetKind.KNOWLEDGE_SOURCE),
                }
            ),
            model_configuration_sha256=_sha(
                _asset_refs(version, SharedAssetKind.MODEL_CONNECTION)
            ),
            egress_policy_version_id=egress_policy.version_id,
            egress_policy_sha256=_sha(egress_policy.model_dump(mode="json")),
            permission_mapping_version_id=permission_mapping.version_id,
            permission_mapping_sha256=_sha(permission_mapping.model_dump(mode="json")),
            permission_epoch=request.permission_epoch,
            institution_authorization_sha256=(
                request.institution_authorization_sha256
            ),
            tool_configuration_sha256=_sha(
                {
                    "assets": _asset_refs(version, SharedAssetKind.TOOL_SOURCE),
                    "tools_yaml": version.contract_bundle.tools_yaml,
                }
            ),
            secret_handle_ids=_secret_handle_ids(version),
            frozen_at=frozen_at,
        )


def _asset_refs(
    version: PublishedAgentVersion,
    kind: SharedAssetKind,
) -> list[dict[str, Any]]:
    return sorted(
        (
            item.model_dump(mode="json")
            for item in version.resolved_shared_asset_versions.versions
            if item.kind is kind
        ),
        key=lambda item: (str(item["asset_id"]), str(item["version_id"])),
    )


def _secret_handle_ids(version: PublishedAgentVersion) -> tuple[str, ...]:
    values: set[str] = set()
    bundle = version.contract_bundle
    _collect_handles(bundle.advanced_fields, values)
    for document in (bundle.agent_yaml, bundle.policy_yaml, bundle.tools_yaml):
        if len(document.encode("utf-8")) > 2 * 1024 * 1024:
            raise RunSnapshotAuthorityError("Published configuration document is too large")
        try:
            parsed = yaml.safe_load(document)
        except yaml.YAMLError as exc:
            raise RunSnapshotAuthorityError(
                "Published configuration document is invalid"
            ) from exc
        _collect_handles(parsed, values)
    return tuple(sorted(values))


def _collect_handles(value: object, output: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {
                "credential_secret_handle",
                "secret_handle",
                "secret_handle_id",
            }:
                if not isinstance(item, str) or not item.strip() or len(item) > 255:
                    raise RunSnapshotAuthorityError("Published Secret Handle id is invalid")
                output.add(item)
            else:
                _collect_handles(item, output)
    elif isinstance(value, list | tuple):
        for item in value:
            _collect_handles(item, output)


def _sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["RunExecutionSnapshotAuthority", "RunSnapshotAuthorityError"]
