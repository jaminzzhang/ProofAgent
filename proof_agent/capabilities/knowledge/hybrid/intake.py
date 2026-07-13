"""Safe, content-free PDF preflight for Hybrid Index intake."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata
from typing import Any, IO
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
_ACTION_CONTAINER_KEYS = {"/A", "/PA", "/Next"}
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
_PDF_TERMINAL_REGION = re.compile(
    rb"startxref[\x00\x09\x0a\x0c\x0d\x20]+"
    rb"(?P<offset>[0-9]+)[\x00\x09\x0a\x0c\x0d\x20]+"
    rb"%%EOF[\x00\x09\x0a\x0c\x0d\x20]*\Z"
)
_PDF_TERMINAL_SCAN_BYTES = 64 * 1024
_PDF_REVISION_STRUCTURE_BYTES = 4 * 1024 * 1024
_SNAPSHOT_MEMORY_BYTES = 1024 * 1024
_FIX = "Upload a safe, unencrypted PDF within the configured Hybrid intake limits."


def preflight_hybrid_pdf(path: Path, *, limits: HybridIntakeLimits) -> HybridPdfPreflight:
    """Validate a quarantined PDF and return deterministic page signals only.

    Native quality is the number of Unicode letter/number characters divided by all
    non-whitespace extracted characters. A page needs OCR when it has fewer than eight
    meaningful characters or a quality ratio below 0.5. Extracted text is never returned.
    """

    snapshot, source_sha256, source_size = _snapshot_safe_source(path, limits.max_file_bytes)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        snapshot.close()
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF support is not installed.") from exc

    try:
        _reject_polyglot_payload(snapshot)
        snapshot.seek(0)
        reader = PdfReader(snapshot, strict=True)
        _validate_terminal_pdf_region(snapshot)
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
    finally:
        snapshot.close()

    return HybridPdfPreflight(
        source_sha256=source_sha256,
        source_size_bytes=source_size,
        page_count=page_count,
        page_profiles=profiles,
    )


def _snapshot_safe_source(path: Path, max_file_bytes: int) -> tuple[IO[bytes], str, int]:
    snapshot: IO[bytes] | None = None
    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        if stat.S_ISLNK(path_metadata.st_mode):
            raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload must be a regular file.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags | no_follow)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload must be a regular file.")
        if _file_identity(path_metadata) != _file_identity(metadata):
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_001", "Hybrid PDF upload changed during validation."
            )
        if metadata.st_size <= 0:
            raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload is empty.")
        if metadata.st_size > max_file_bytes:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_002",
                f"Hybrid PDF upload exceeds {max_file_bytes} bytes.",
            )
        digest = hashlib.sha256()
        total = 0
        snapshot = tempfile.SpooledTemporaryFile(max_size=_SNAPSHOT_MEMORY_BYTES, mode="w+b")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            signature = handle.read(len(_PDF_SIGNATURE))
            if signature != _PDF_SIGNATURE:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_001", "Hybrid PDF upload is missing a PDF content signature."
                )
            digest.update(signature)
            snapshot.write(signature)
            total += len(signature)
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                total += len(chunk)
                if total > max_file_bytes:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_002",
                        f"Hybrid PDF upload exceeds {max_file_bytes} bytes.",
                    )
                digest.update(chunk)
                snapshot.write(chunk)
        if total != metadata.st_size:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_001", "Hybrid PDF upload changed during validation."
            )
        snapshot.seek(0)
        return snapshot, digest.hexdigest(), total
    except ProofAgentError:
        if snapshot is not None:
            snapshot.close()
        raise
    except OSError as exc:
        if snapshot is not None:
            snapshot.close()
        raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload could not be read.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _file_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


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


def _reject_polyglot_payload(source: IO[bytes]) -> None:
    """Reject source bytes that are simultaneously a structurally valid ZIP archive."""

    try:
        source.seek(0)
        if zipfile.is_zipfile(source):
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_009",
                "Hybrid PDF upload contains an appended archive or executable payload.",
            )
    except ProofAgentError:
        raise
    except OSError as exc:
        raise _hybrid_error("PA_HYBRID_INTAKE_001", "Hybrid PDF upload could not be read.") from exc


def _validate_terminal_pdf_region(source: IO[bytes]) -> None:
    startxref_offset = _last_marker_offset(source, b"startxref")
    if startxref_offset is None:
        return
    source.seek(0, os.SEEK_END)
    size = source.tell()
    terminal_region_size = size - startxref_offset
    if terminal_region_size > _PDF_TERMINAL_SCAN_BYTES:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_009",
            "Hybrid PDF upload contains an appended archive or executable payload.",
        )
    source.seek(startxref_offset)
    terminal_region = source.read(terminal_region_size)
    match = _PDF_TERMINAL_REGION.fullmatch(terminal_region)
    if match is None:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_009",
            "Hybrid PDF upload contains an appended archive or executable payload.",
        )
    xref_offset = int(match.group("offset"))
    if xref_offset >= startxref_offset:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF startxref is invalid.")
    previous_revision = _previous_revision_before(source, startxref_offset)
    if previous_revision is None:
        return

    previous_eof_end, previous_xref_offset = previous_revision
    if xref_offset <= previous_eof_end:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_009",
            "Hybrid PDF upload contains bytes outside a valid incremental revision.",
        )
    _validate_incremental_revision(
        source,
        previous_eof_end=previous_eof_end,
        previous_xref_offset=previous_xref_offset,
        xref_offset=xref_offset,
        startxref_offset=startxref_offset,
    )


def _last_marker_offset(
    source: IO[bytes],
    marker: bytes,
    *,
    before: int | None = None,
) -> int | None:
    source.seek(0)
    last_offset: int | None = None
    offset = 0
    overlap = b""
    remaining = before
    while remaining is None or remaining > 0:
        read_size = _HASH_CHUNK_BYTES if remaining is None else min(_HASH_CHUNK_BYTES, remaining)
        chunk = source.read(read_size)
        if not chunk:
            break
        searchable = overlap + chunk
        searchable_offset = offset - len(overlap)
        marker_index = searchable.find(marker)
        while marker_index >= 0:
            last_offset = searchable_offset + marker_index
            marker_index = searchable.find(marker, marker_index + 1)
        offset += len(chunk)
        if remaining is not None:
            remaining -= len(chunk)
        overlap = searchable[-(len(marker) - 1) :]
    return last_offset


def _previous_revision_before(source: IO[bytes], before: int) -> tuple[int, int] | None:
    eof_offsets = _marker_offsets(source, b"%%EOF", before=before)
    startxref_offsets = _marker_offsets(source, b"startxref", before=before)
    for eof_offset in reversed(eof_offsets):
        eof_end = eof_offset + len(b"%%EOF")
        for previous_startxref in reversed(startxref_offsets):
            if previous_startxref >= eof_offset:
                continue
            if eof_end - previous_startxref > _PDF_TERMINAL_SCAN_BYTES:
                break
            source.seek(previous_startxref)
            revision_end = source.read(eof_end - previous_startxref)
            match = _PDF_TERMINAL_REGION.fullmatch(revision_end)
            if match is not None:
                return eof_end, int(match.group("offset"))
    return None


def _marker_offsets(source: IO[bytes], marker: bytes, *, before: int) -> list[int]:
    offsets: list[int] = []
    source.seek(0)
    offset = 0
    overlap = b""
    remaining = before
    while remaining > 0:
        chunk = source.read(min(_HASH_CHUNK_BYTES, remaining))
        if not chunk:
            break
        searchable = overlap + chunk
        searchable_offset = offset - len(overlap)
        marker_index = searchable.find(marker)
        while marker_index >= 0:
            absolute_offset = searchable_offset + marker_index
            if not offsets or offsets[-1] != absolute_offset:
                offsets.append(absolute_offset)
            marker_index = searchable.find(marker, marker_index + 1)
        offset += len(chunk)
        remaining -= len(chunk)
        overlap = searchable[-(len(marker) - 1) :]
    return offsets


def _validate_incremental_revision(
    source: IO[bytes],
    *,
    previous_eof_end: int,
    previous_xref_offset: int,
    xref_offset: int,
    startxref_offset: int,
) -> None:
    structure_size = startxref_offset - xref_offset
    if structure_size <= 0 or structure_size > _PDF_REVISION_STRUCTURE_BYTES:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental revision is invalid.")
    source.seek(xref_offset)
    structure = source.read(structure_size)
    if not (
        structure.startswith(b"xref")
        or re.match(
            rb"[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+obj\b", structure
        )
    ):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental xref is invalid.")
    prev_pattern = (
        rb"/Prev[\x00\x09\x0a\x0c\x0d\x20]+"
        + str(previous_xref_offset).encode("ascii")
        + rb"(?![0-9])"
    )
    if re.search(prev_pattern, structure) is None:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental /Prev is invalid.")

    prefix_size = xref_offset - previous_eof_end
    source.seek(previous_eof_end)
    prefix_start = source.read(min(prefix_size, 128)).lstrip(b"\x00\x09\x0a\x0c\x0d\x20")
    if not prefix_start:
        return
    if (
        re.match(
            rb"[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+obj\b",
            prefix_start,
        )
        is None
    ):
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_009",
            "Hybrid PDF upload contains bytes outside a valid incremental revision.",
        )
    source.seek(max(previous_eof_end, xref_offset - 128))
    prefix_end = source.read(xref_offset - max(previous_eof_end, xref_offset - 128)).rstrip(
        b"\x00\x09\x0a\x0c\x0d\x20"
    )
    if not prefix_end.endswith(b"endobj"):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental objects are invalid.")


def _reject_unsafe_pdf_objects(reader: Any) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    pending: list[tuple[Any, str | None]] = [(reader.trailer, None)]
    seen: set[tuple[tuple[int, int] | int, bool]] = set()
    while pending:
        item, parent_key = pending.pop()
        in_action_container = parent_key in _ACTION_CONTAINER_KEYS
        if isinstance(item, IndirectObject):
            identity: tuple[int, int] | int = (item.idnum, item.generation)
            seen_key = (identity, in_action_container)
            if seen_key in seen:
                continue
            seen.add(seen_key)
            if len(seen) > _MAX_VISITED_PDF_OBJECTS:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF object graph exceeds safety limits."
                )
            item = item.get_object()
        elif isinstance(item, (DictionaryObject, ArrayObject)):
            identity = id(item)
            seen_key = (identity, in_action_container)
            if seen_key in seen:
                continue
            seen.add(seen_key)

        if isinstance(item, DictionaryObject):
            keys = {str(key) for key in item.keys()}
            action_type = item.get(NameObject("/S"))
            object_type = item.get(NameObject("/Type"))
            if (
                keys & _ACTIVE_KEYS
                or (in_action_container and "/S" in keys)
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
            pending.extend((value, str(key)) for key, value in item.items())
        elif isinstance(item, ArrayObject):
            pending.extend((value, parent_key) for value in item)


def _hybrid_error(code: str, message: str) -> ProofAgentError:
    return ProofAgentError(code, message, _FIX)
