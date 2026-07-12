from __future__ import annotations

from enum import Enum
from pathlib import Path


class ErrorCode(str, Enum):
    """Stable user-facing error codes grouped by Proof Agent subsystem."""

    PA_CONFIG_001 = "PA_CONFIG_001"
    PA_CONFIG_002 = "PA_CONFIG_002"
    PA_SCHEMA_001 = "PA_SCHEMA_001"
    PA_SCHEMA_002 = "PA_SCHEMA_002"
    PA_KNOWLEDGE_001 = "PA_KNOWLEDGE_001"
    PA_KNOWLEDGE_002 = "PA_KNOWLEDGE_002"
    PA_INGESTION_001 = "PA_INGESTION_001"
    PA_INGESTION_002 = "PA_INGESTION_002"
    PA_INGESTION_003 = "PA_INGESTION_003"
    PA_INGESTION_004 = "PA_INGESTION_004"
    PA_INGESTION_005 = "PA_INGESTION_005"
    PA_HYBRID_INTAKE_001 = "PA_HYBRID_INTAKE_001"
    PA_HYBRID_INTAKE_002 = "PA_HYBRID_INTAKE_002"
    PA_HYBRID_INTAKE_003 = "PA_HYBRID_INTAKE_003"
    PA_HYBRID_INTAKE_004 = "PA_HYBRID_INTAKE_004"
    PA_HYBRID_INTAKE_005 = "PA_HYBRID_INTAKE_005"
    PA_HYBRID_INTAKE_006 = "PA_HYBRID_INTAKE_006"
    PA_HYBRID_INTAKE_007 = "PA_HYBRID_INTAKE_007"
    PA_HYBRID_INTAKE_008 = "PA_HYBRID_INTAKE_008"
    PA_RETRIEVAL_001 = "PA_RETRIEVAL_001"
    PA_REACT_001 = "PA_REACT_001"
    PA_RUNTIME_001 = "PA_RUNTIME_001"
    PA_MODEL_001 = "PA_MODEL_001"
    PA_MODEL_002 = "PA_MODEL_002"
    PA_MODEL_003 = "PA_MODEL_003"
    PA_MODEL_004 = "PA_MODEL_004"
    PA_MODEL_CONNECTION_001 = "PA_MODEL_CONNECTION_001"
    PA_MODEL_CONNECTION_002 = "PA_MODEL_CONNECTION_002"
    PA_POLICY_001 = "PA_POLICY_001"
    PA_CUSTOMER_001 = "PA_CUSTOMER_001"
    PA_TOOL_001 = "PA_TOOL_001"
    PA_TOOL_PROPOSAL_001 = "PA_TOOL_PROPOSAL_001"
    PA_TOOL_SOURCE_001 = "PA_TOOL_SOURCE_001"
    PA_TOOL_SOURCE_002 = "PA_TOOL_SOURCE_002"
    PA_APPROVAL_001 = "PA_APPROVAL_001"
    PA_DOCKER_001 = "PA_DOCKER_001"
    PA_RUNS_001 = "PA_RUNS_001"
    PA_AUDIT_001 = "PA_AUDIT_001"
    PA_RECEIPT_001 = "PA_RECEIPT_001"
    PA_SECRET_001 = "PA_SECRET_001"


class ProofAgentError(Exception):
    """Exception that carries an actionable fix and optional artifact references."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        fix: str,
        *,
        artifact_path: Path | str | None = None,
        docs_path: Path | str | None = None,
    ) -> None:
        error_code = code if isinstance(code, ErrorCode) else ErrorCode(code)
        self.code = error_code.value
        self.message = message
        self.fix = fix
        self.artifact_path = Path(artifact_path) if artifact_path is not None else None
        self.docs_path = Path(docs_path) if docs_path is not None else None
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"{self.code}: {self.message}", f"Fix: {self.fix}"]
        if self.artifact_path is not None:
            lines.append(f"Artifact: {self.artifact_path}")
        if self.docs_path is not None:
            lines.append(f"Docs: {self.docs_path}")
        return "\n".join(lines)
