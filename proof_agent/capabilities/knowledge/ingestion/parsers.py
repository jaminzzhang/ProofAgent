"""Fail-closed quarantine validator registry and local document parsers."""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from proof_agent.capabilities.knowledge.ingestion.contracts import (
    KnowledgeDocumentParser,
    ParsedKnowledgeDocument,
    ParserMetadata,
)
from proof_agent.errors import ProofAgentError

_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_MARKDOWN_CONTENT_TYPES = {"text/markdown", "text/plain"}
_PDF_CONTENT_TYPE = "application/pdf"
_PDF_SIGNATURE = b"%PDF-"
_UNSAFE_MARKDOWN_SIGNATURES = (
    _PDF_SIGNATURE,
    b"MZ",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x7fELF",
)
_UPLOAD_FIX = (
    "Upload a supported UTF-8 Markdown file or a text-based, unencrypted PDF up to 500 pages."
)


class MarkdownKnowledgeDocumentParser:
    """Normalize one validated UTF-8 Markdown upload."""

    @property
    def parser_metadata(self) -> ParserMetadata:
        return ParserMetadata(
            adapter="markdown",
            adapter_contract_version="1",
            library_version=None,
            fingerprint_identity="markdown:utf-8:v1",
        )

    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument:
        if _normalized_content_type(content_type) not in _MARKDOWN_CONTENT_TYPES:
            raise _invalid_upload("Markdown upload has an unsupported declared MIME type.")
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _invalid_upload("Markdown upload must contain UTF-8 text.") from exc
        except OSError as exc:
            raise _invalid_upload("Markdown upload could not be read.") from exc

        if _has_unsafe_markdown_signature(content):
            raise _invalid_upload("Markdown upload content signature is not supported.")

        normalized_text = _normalize_text(text)
        if not normalized_text.strip():
            raise _invalid_upload("Markdown upload does not contain meaningful text.")
        return ParsedKnowledgeDocument(
            text=normalized_text,
            page_count=None,
            parser_metadata=_metadata_with_text_hash(self.parser_metadata, normalized_text),
        )


class PdfKnowledgeDocumentParser:
    """Extract normalized Unicode text from one validated PDF upload using pypdf."""

    @property
    def parser_metadata(self) -> ParserMetadata:
        try:
            library_version = version("pypdf")
        except PackageNotFoundError as exc:
            raise _invalid_upload("PDF parsing support is not installed.") from exc
        return ParserMetadata(
            adapter="pypdf",
            adapter_contract_version="1",
            library_version=library_version,
            fingerprint_identity=f"pypdf:v1@{library_version}",
        )

    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument:
        if _normalized_content_type(content_type) != _PDF_CONTENT_TYPE:
            raise _invalid_upload("PDF upload has an unsupported declared MIME type.")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise _invalid_upload("PDF parsing support is not installed.") from exc

        try:
            reader = PdfReader(path)
            if reader.is_encrypted and not _decrypt_pdf_with_empty_password(reader):
                raise _invalid_upload("Encrypted PDF uploads require a password and are not supported.")
            page_count = len(reader.pages)
            if page_count > 500:
                raise _invalid_upload("PDF upload exceeds the 500-page limit.")
            normalized_pages = [_normalize_text(page.extract_text() or "") for page in reader.pages]
        except ProofAgentError:
            raise
        except Exception as exc:
            raise _invalid_upload("PDF upload is malformed or could not be parsed.") from exc

        normalized_text = "\n\n".join(normalized_pages)
        if not normalized_text.strip():
            raise _invalid_upload("PDF upload does not contain extractable text.")
        return ParsedKnowledgeDocument(
            text=normalized_text,
            page_count=page_count,
            parser_metadata=_metadata_with_text_hash(self.parser_metadata, normalized_text),
        )


class KnowledgeDocumentParserRegistry:
    """Select a parser only after extension, MIME, and signature checks agree."""

    def parse(self, path: Path, *, filename: str, content_type: str) -> ParsedKnowledgeDocument:
        parser = self.parser_for_upload(path, filename=filename, content_type=content_type)
        return parser.parse(path, content_type)

    def parser_for_upload(
        self,
        path: Path,
        *,
        filename: str,
        content_type: str,
    ) -> KnowledgeDocumentParser:
        suffix = Path(filename).suffix.lower()
        normalized_content_type = _normalized_content_type(content_type)
        signature = _read_signature(path)

        if suffix in _MARKDOWN_SUFFIXES:
            if normalized_content_type not in _MARKDOWN_CONTENT_TYPES:
                raise _invalid_upload("Markdown upload extension and declared MIME type disagree.")
            if _has_unsafe_markdown_signature(signature):
                raise _invalid_upload("Markdown upload content signature is not supported.")
            return MarkdownKnowledgeDocumentParser()

        if suffix == ".pdf":
            if normalized_content_type != _PDF_CONTENT_TYPE:
                raise _invalid_upload("PDF upload extension and declared MIME type disagree.")
            if not signature.startswith(_PDF_SIGNATURE):
                raise _invalid_upload("PDF upload is missing a PDF content signature.")
            return PdfKnowledgeDocumentParser()

        raise _invalid_upload("Knowledge upload type is not supported.")


def parse_quarantined_upload(
    path: Path,
    *,
    filename: str,
    content_type: str,
) -> ParsedKnowledgeDocument:
    """Validate and parse one staged quarantine upload."""

    return KnowledgeDocumentParserRegistry().parse(
        path,
        filename=filename,
        content_type=content_type,
    )


def _normalized_content_type(content_type: str) -> str:
    return content_type.partition(";")[0].strip().lower()


def _read_signature(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(8)
    except OSError as exc:
        raise _invalid_upload("Knowledge upload could not be read.") from exc


def _has_unsafe_markdown_signature(content: bytes) -> bool:
    return any(content.startswith(signature) for signature in _UNSAFE_MARKDOWN_SIGNATURES)


def _decrypt_pdf_with_empty_password(reader: object) -> bool:
    try:
        result = reader.decrypt("")  # type: ignore[attr-defined]
        if result == 0:
            return False
        len(reader.pages)  # type: ignore[attr-defined]
    except Exception:
        return False
    return True


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _metadata_with_text_hash(metadata: ParserMetadata, text: str) -> ParserMetadata:
    return replace(metadata, parsed_text_sha256=sha256(text.encode("utf-8")).hexdigest())


def _invalid_upload(message: str) -> ProofAgentError:
    return ProofAgentError("PA_INGESTION_002", message, _UPLOAD_FIX)
