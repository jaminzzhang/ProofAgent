"""Local Index ingestion configuration and document parser boundary."""

from proof_agent.capabilities.knowledge.ingestion.configuration import (
    ingestion_model_config_from_build_spec,
    local_index_engine_version,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import (
    KnowledgeDocumentParser,
    ParsedKnowledgeDocument,
    ParserMetadata,
)
from proof_agent.capabilities.knowledge.ingestion.fingerprint import (
    ingestion_config_fingerprint,
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
    "MarkdownKnowledgeDocumentParser",
    "ParsedKnowledgeDocument",
    "ParserMetadata",
    "PdfKnowledgeDocumentParser",
    "ingestion_config_fingerprint",
    "ingestion_model_config_from_build_spec",
    "local_index_engine_version",
    "parse_quarantined_upload",
]
