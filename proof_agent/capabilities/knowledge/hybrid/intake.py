"""Safe, content-free PDF preflight for Hybrid Index intake."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import stat
import unicodedata
from typing import Any
import zipfile

from proof_agent.capabilities.knowledge.ingestion.contracts import (
    HybridIntakeLimits,
    HybridPdfPageProfile,
    HybridPdfPreflight,
)
from proof_agent.errors import ProofAgentError

_PDF_SIGNATURE = b"%PDF-"
_HASH_CHUNK_BYTES = 1024 * 1024
_MIN_MEANINGFUL_CHARACTERS = 8
_MIN_NATIVE_TEXT_QUALITY_RATIO = 0.5
_ACTIVE_KEYS = {"/OpenAction", "/AA", "/JS", "/JavaScript", "/Launch"}
_ACTION_TYPES = {
    "/GoTo",
    "/GoToR",
    "/GoToE",
    "/Launch",
    "/Thread",
    "/URI",
    "/Sound",
    "/Movie",
    "/Hide",
    "/Named",
    "/SubmitForm",
    "/ResetForm",
    "/ImportData",
    "/JavaScript",
    "/SetOCGState",
    "/Rendition",
    "/Trans",
    "/GoTo3DView",
    "/RichMediaExecute",
}
_EMBEDDED_KEYS = {"/EmbeddedFiles", "/EF", "/AF"}
_MAX_VISITED_PDF_OBJECTS = 100_000
_PDF_EOF_MARKER = b"%%EOF"
_PDF_TRAILING_WHITESPACE = frozenset(b"\x00\x09\x0a\x0c\x0d\x20")
_FIX = "Upload a safe, unencrypted PDF within the configured Hybrid intake limits."


def preflight_hybrid_pdf(path: Path, *, limits: HybridIntakeLimits) -> HybridPdfPreflight:
    """Validate a quarantined PDF and return deterministic page signals only.

    Native quality is the number of Unicode letter/number characters divided by all
    non-whitespace extracted characters. A page needs OCR when it has fewer than eight
    meaningful characters or a quality ratio below 0.5. Extracted text is never returned.
    """

    source_sha256, source_size = _hash_safe_source(path, limits.max_file_bytes)
    _reject_polyglot_payload(path)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF support is not installed.") from exc

    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_003", "Encrypted Hybrid PDF uploads are not supported."
            )
        page_count = len(reader.pages)
        if page_count == 0:
            raise _hybrid_error("PA_HYBRID_INTAKE_004", "Hybrid PDF upload has no pages.")
        if page_count > limits.max_pdf_pages:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_005",
                f"Hybrid PDF upload exceeds the {limits.max_pdf_pages}-page limit.",
            )
        _reject_unsafe_pdf_objects(reader)
        profiles = tuple(_profile_page(page, number) for number, page in enumerate(reader.pages, 1))
    except ProofAgentError:
        raise
    except Exception as exc:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF upload is malformed or could not be parsed."
        ) from exc

    return HybridPdfPreflight(
        source_sha256=source_sha256,
        source_size_bytes=source_size,
        page_count=page_count,
        page_profiles=profiles,
    )


def _hash_safe_source(path: Path, max_file_bytes: int) -> tuple[str, int]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload must be a regular file.")
        if metadata.st_size <= 0:
            raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload is empty.")
        if metadata.st_size > max_file_bytes:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_002",
                f"Hybrid PDF upload exceeds {max_file_bytes} bytes.",
            )
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            signature = handle.read(len(_PDF_SIGNATURE))
            if signature != _PDF_SIGNATURE:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_001", "Hybrid PDF upload is missing a PDF content signature."
                )
            digest.update(signature)
            total += len(signature)
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                total += len(chunk)
                if total > max_file_bytes:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_002",
                        f"Hybrid PDF upload exceeds {max_file_bytes} bytes.",
                    )
                digest.update(chunk)
        if total != metadata.st_size:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_001", "Hybrid PDF upload changed during validation."
            )
        return digest.hexdigest(), total
    except ProofAgentError:
        raise
    except OSError as exc:
        raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload could not be read.") from exc


def _profile_page(page: Any, page_number: int) -> HybridPdfPageProfile:
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF upload contains invalid page dimensions."
        )
    extracted = unicodedata.normalize("NFC", page.extract_text() or "")
    non_whitespace = [character for character in extracted if not character.isspace()]
    meaningful_count = sum(
        unicodedata.category(character)[0] in {"L", "N"} for character in non_whitespace
    )
    quality_ratio = meaningful_count / len(non_whitespace) if non_whitespace else 0.0
    return HybridPdfPageProfile(
        page_number=page_number,
        width_points=width,
        height_points=height,
        native_extracted_character_count=len(non_whitespace),
        native_text_quality_ratio=quality_ratio,
        requires_ocr=(
            meaningful_count < _MIN_MEANINGFUL_CHARACTERS
            or quality_ratio < _MIN_NATIVE_TEXT_QUALITY_RATIO
        ),
    )


def _reject_polyglot_payload(path: Path) -> None:
    """Reject a PDF that is also an archive or carries bytes after its final EOF marker."""

    try:
        if zipfile.is_zipfile(path) or _has_non_whitespace_after_final_pdf_eof(path):
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_009",
                "Hybrid PDF upload contains an appended archive or executable payload.",
            )
    except ProofAgentError:
        raise
    except OSError as exc:
        raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload could not be read.") from exc


def _has_non_whitespace_after_final_pdf_eof(path: Path) -> bool:
    last_eof_end: int | None = None
    offset = 0
    overlap = b""
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            searchable = overlap + chunk
            searchable_offset = offset - len(overlap)
            marker_index = searchable.find(_PDF_EOF_MARKER)
            while marker_index >= 0:
                last_eof_end = searchable_offset + marker_index + len(_PDF_EOF_MARKER)
                marker_index = searchable.find(_PDF_EOF_MARKER, marker_index + 1)
            offset += len(chunk)
            overlap = searchable[-(len(_PDF_EOF_MARKER) - 1) :]

        if last_eof_end is None:
            return False
        handle.seek(last_eof_end)
        while trailing := handle.read(_HASH_CHUNK_BYTES):
            if any(byte not in _PDF_TRAILING_WHITESPACE for byte in trailing):
                return True
    return False


def _reject_unsafe_pdf_objects(reader: Any) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    pending: list[Any] = [reader.trailer]
    seen: set[tuple[int, int] | int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, IndirectObject):
            identity: tuple[int, int] | int = (item.idnum, item.generation)
            if identity in seen:
                continue
            seen.add(identity)
            if len(seen) > _MAX_VISITED_PDF_OBJECTS:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF object graph exceeds safety limits."
                )
            item = item.get_object()
        elif isinstance(item, (DictionaryObject, ArrayObject)):
            identity = id(item)
            if identity in seen:
                continue
            seen.add(identity)

        if isinstance(item, DictionaryObject):
            keys = {str(key) for key in item.keys()}
            action_type = item.get(NameObject("/S"))
            object_type = item.get(NameObject("/Type"))
            if (
                keys & _ACTIVE_KEYS
                or str(action_type) in _ACTION_TYPES
                or object_type == NameObject("/Action")
            ):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_007", "Hybrid PDF upload contains active content."
                )
            if keys & _EMBEDDED_KEYS or item.get(NameObject("/Type")) == NameObject(
                "/EmbeddedFile"
            ):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_008", "Hybrid PDF upload contains embedded files."
                )
            pending.extend(item.values())
        elif isinstance(item, ArrayObject):
            pending.extend(item)


def _hybrid_error(code: str, message: str) -> ProofAgentError:
    return ProofAgentError(code, message, _FIX)
