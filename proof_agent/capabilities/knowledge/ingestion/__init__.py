"""Local Index ingestion configuration and document parser boundary."""

from proof_agent.capabilities.knowledge.ingestion.configuration import (
    ingestion_model_config_from_build_spec,
    local_index_engine_version,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import (
    KnowledgeDocumentParser,
    KnowledgeWorkerClaimSelection,
    KnowledgeWorkerDiagnostic,
    KnowledgeWorkerTaskClaim,
    ParsedKnowledgeDocument,
    ParserMetadata,
)
from proof_agent.capabilities.knowledge.ingestion.fingerprint import (
    ingestion_config_fingerprint,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
    HybridKnowledgeWorker,
    HybridParserBuildOutput,
    HybridPrivateParserBuildConfig,
    HybridVendorArtifact,
    HybridVendorArtifactRef,
    HybridWorkerOutcome,
    LocalManagedOriginalStore,
    LocalStoreHybridQuarantinePromoter,
    LocalStoreHybridWorkerLifecycle,
    ReviewRequiredError,
    TransientKnowledgeServiceError,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.knowledge.ingestion.parsers import (
    KnowledgeDocumentParserRegistry,
    MarkdownKnowledgeDocumentParser,
    PdfKnowledgeDocumentParser,
    parse_quarantined_upload,
)

__all__ = [
    "KnowledgeDocumentParser",
    "KnowledgeDocumentParserRegistry",
    "HybridArtifactBuildRequest",
    "HybridArtifactBuildResult",
    "HybridInsuranceMetadataArtifact",
    "HybridKnowledgeWorker",
    "HybridParserBuildOutput",
    "HybridPrivateParserBuildConfig",
    "HybridVendorArtifact",
    "HybridVendorArtifactRef",
    "HybridWorkerOutcome",
    "LocalManagedOriginalStore",
    "LocalStoreHybridQuarantinePromoter",
    "LocalStoreHybridWorkerLifecycle",
    "KnowledgeWorkerClaimSelection",
    "KnowledgeWorkerDiagnostic",
    "KnowledgeWorkerTaskClaim",
    "MarkdownKnowledgeDocumentParser",
    "ParsedKnowledgeDocument",
    "ParserMetadata",
    "PdfKnowledgeDocumentParser",
    "ReviewRequiredError",
    "TransientKnowledgeServiceError",
    "hybrid_build_request_sha256",
    "ingestion_config_fingerprint",
    "ingestion_model_config_from_build_spec",
    "local_index_engine_version",
    "parse_quarantined_upload",
]
