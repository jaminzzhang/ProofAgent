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
import zlib

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
_MAX_NATIVE_TEXT_SAMPLE_CHARS = 4096
_MAX_NATIVE_TEXT_CALLBACKS = 4096
_MAX_PAGE_CONTENT_DECODED_BYTES = 2 * 1024 * 1024
_MAX_FORM_XOBJECT_DEPTH = 16
_MAX_FORM_XOBJECTS = 256
_MAX_FORM_DO_INVOCATIONS = 64
_MAX_XOBJECT_RESOURCE_ENTRIES = 1024
_MAX_FONT_RESOURCE_ENTRIES = 1024
_MAX_CONTENT_OPERATIONS = 100_000
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
_MAX_INDEXED_PDF_OBJECTS = 100_000
_MAX_PDF_REVISIONS = 32
_MAX_REVISION_MARKER_CANDIDATES = 256
_MAX_HISTORICAL_REVISION_BYTES = 100 * 1024 * 1024
_PDF_TERMINAL_REGION = re.compile(
    rb"startxref[\x00\x09\x0a\x0c\x0d\x20]+"
    rb"(?P<offset>[0-9]+)[\x00\x09\x0a\x0c\x0d\x20]+"
    rb"%%EOF[\x00\x09\x0a\x0c\x0d\x20]*\Z"
)
_PDF_TERMINAL_SCAN_BYTES = 64 * 1024
_PDF_REVISION_STRUCTURE_BYTES = 4 * 1024 * 1024
_PDF_BOUNDARY_SCAN_BYTES = 4096
_PDF_WHITESPACE = b"\x00\x09\x0a\x0c\x0d\x20"
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
        _reject_unsafe_historical_revisions(snapshot, PdfReader)
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
    extracted = unicodedata.normalize("NFC", _sample_native_page_text(page))
    non_whitespace_count = sum(not character.isspace() for character in extracted)
    meaningful_count = sum(
        not character.isspace() and unicodedata.category(character)[0] in {"L", "N"}
        for character in extracted
    )
    quality_ratio = meaningful_count / non_whitespace_count if non_whitespace_count else 0.0
    return HybridPdfPageProfile(
        page_number=page_number,
        width_points=width,
        height_points=height,
        native_extracted_character_count=non_whitespace_count,
        native_text_quality_ratio=quality_ratio,
        requires_ocr=(
            meaningful_count < _MIN_MEANINGFUL_CHARACTERS
            or quality_ratio < _MIN_NATIVE_TEXT_QUALITY_RATIO
        ),
    )


class _NativeTextSampleComplete(Exception):
    pass


class _NativeTextExtractionLimit(Exception):
    pass


def _sample_native_page_text(page: Any) -> str:
    if not _validate_bounded_page_content(page):
        return ""
    chunks: list[str] = []
    sampled_characters = 0
    callback_count = 0

    def collect(text: str, *_args: Any) -> None:
        nonlocal callback_count, sampled_characters
        callback_count += 1
        if callback_count > _MAX_NATIVE_TEXT_CALLBACKS:
            raise _NativeTextExtractionLimit
        remaining = _MAX_NATIVE_TEXT_SAMPLE_CHARS - sampled_characters
        if remaining <= 0:
            raise _NativeTextSampleComplete
        chunks.append(text[:remaining])
        sampled_characters += min(len(text), remaining)
        if len(text) >= remaining:
            raise _NativeTextSampleComplete

    try:
        page.extract_text(visitor_text=collect)
    except _NativeTextSampleComplete:
        pass
    except _NativeTextExtractionLimit as exc:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF native text extraction exceeds safety limits.",
        ) from exc
    return "".join(chunks)


def _validate_bounded_page_content(page: Any) -> bool:
    from pypdf.generic import ArrayObject, IndirectObject, NameObject

    decoded_page_content: list[bytes] = []
    try:
        contents = page.raw_get(NameObject("/Contents"))
    except KeyError:
        contents = None

    remaining = _MAX_PAGE_CONTENT_DECODED_BYTES
    pending = (
        list(contents)
        if isinstance(contents, ArrayObject)
        else ([] if contents is None else [contents])
    )
    while pending:
        item = pending.pop()
        if isinstance(item, IndirectObject):
            item = item.get_object()
        if isinstance(item, ArrayObject):
            pending.extend(item)
            continue
        remaining, decoded = _charge_bounded_content_stream(item, remaining)
        decoded_page_content.append(decoded)

    resources = page.get_inherited(key="/Resources", default=None)
    if resources is not None:
        _remaining, form_lookup = _validate_bounded_resources(resources, remaining)
        _validate_form_do_work(decoded_page_content, resources, form_lookup)
    return any(decoded_page_content)


def _charge_bounded_content_stream(stream: Any, remaining: int) -> tuple[int, bytes]:
    from pypdf.generic import ArrayObject, NameObject, StreamObject

    if not isinstance(stream, StreamObject):
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF page content stream is invalid.",
        )
    raw_data = stream._data  # pypdf retains encoded stream bytes without decoding them.
    filters = stream.get(NameObject("/Filter"))
    if filters is None:
        decoded = raw_data
    else:
        filter_names = (
            tuple(str(value) for value in filters)
            if isinstance(filters, ArrayObject)
            else (str(filters),)
        )
        if filter_names not in {("/FlateDecode",), ("/Fl",)}:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF page content filter cannot be sampled safely.",
            )
        decoded = _bounded_flate_decoded_data(raw_data, remaining)
    remaining -= len(decoded)
    if remaining < 0:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF decoded page content exceeds safety limits.",
        )
    return remaining, decoded


def _validate_bounded_resources(
    resources: Any,
    remaining: int,
) -> tuple[int, dict[tuple[int, str], tuple[tuple[int, int] | int, bytes, Any | None]]]:
    from pypdf.generic import DictionaryObject, IndirectObject, NameObject, StreamObject

    pending: list[tuple[Any, int]] = [(resources, 0)]
    seen_forms: set[tuple[int, int] | int] = set()
    seen_resources: set[int] = set()
    seen_font_streams: set[tuple[int, int] | int] = set()
    form_count = 0
    resource_entry_count = 0
    font_entry_count = 0
    form_lookup: dict[tuple[int, str], tuple[tuple[int, int] | int, bytes, Any | None]] = {}
    while pending:
        current_resources, depth = pending.pop()
        if isinstance(current_resources, IndirectObject):
            current_resources = current_resources.get_object()
        if not isinstance(current_resources, DictionaryObject):
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF Form XObject resources are invalid.",
            )
        resources_identity = id(current_resources)
        if resources_identity in seen_resources:
            continue
        seen_resources.add(resources_identity)

        fonts = current_resources.get(NameObject("/Font"))
        if isinstance(fonts, IndirectObject):
            fonts = fonts.get_object()
        if fonts is not None:
            if not isinstance(fonts, DictionaryObject):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF Font resources are invalid."
                )
            for font_candidate in fonts.values():
                font_entry_count += 1
                if font_entry_count > _MAX_FONT_RESOURCE_ENTRIES:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF Font resource work exceeds safety limits.",
                    )
                font = (
                    font_candidate.get_object()
                    if isinstance(font_candidate, IndirectObject)
                    else font_candidate
                )
                if not isinstance(font, DictionaryObject):
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006", "Hybrid PDF Font resource is invalid."
                    )
                remaining = _charge_bounded_font_streams(
                    font,
                    remaining,
                    seen_font_streams,
                )

        xobjects = current_resources.get(NameObject("/XObject"))
        if isinstance(xobjects, IndirectObject):
            xobjects = xobjects.get_object()
        if xobjects is None:
            continue
        if not isinstance(xobjects, DictionaryObject):
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF XObject resources are invalid.",
            )
        for name, candidate in xobjects.items():
            resource_entry_count += 1
            if resource_entry_count > _MAX_XOBJECT_RESOURCE_ENTRIES:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006",
                    "Hybrid PDF XObject resource work exceeds safety limits.",
                )
            if isinstance(candidate, IndirectObject):
                identity: tuple[int, int] | int = (candidate.idnum, candidate.generation)
                form = candidate.get_object()
            else:
                identity = id(candidate)
                form = candidate
            if not isinstance(form, StreamObject):
                raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF XObject is invalid.")
            subtype = str(form.get(NameObject("/Subtype")))
            if subtype == "/Image":
                continue
            if subtype != "/Form":
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006",
                    "Hybrid PDF XObject subtype cannot be sampled safely.",
                )
            if identity in seen_forms:
                existing = next(
                    (value for value in form_lookup.values() if value[0] == identity),
                    None,
                )
                if existing is not None:
                    form_lookup[(resources_identity, str(name))] = existing
                continue
            seen_forms.add(identity)
            form_count += 1
            if form_count > _MAX_FORM_XOBJECTS or depth + 1 > _MAX_FORM_XOBJECT_DEPTH:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006",
                    "Hybrid PDF Form XObject graph exceeds safety limits.",
                )
            remaining, decoded_form = _charge_bounded_content_stream(form, remaining)
            nested_resources = form.get(NameObject("/Resources"))
            form_lookup[(resources_identity, str(name))] = (
                identity,
                decoded_form,
                nested_resources,
            )
            if nested_resources is not None:
                pending.append((nested_resources, depth + 1))
    return remaining, form_lookup


def _charge_bounded_font_streams(
    font: Any,
    remaining: int,
    seen_streams: set[tuple[int, int] | int],
) -> int:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    font_dictionaries = [font]
    descendants = font.get(NameObject("/DescendantFonts"))
    if isinstance(descendants, IndirectObject):
        descendants = descendants.get_object()
    if isinstance(descendants, ArrayObject):
        font_dictionaries.extend(
            item.get_object() if isinstance(item, IndirectObject) else item for item in descendants
        )

    stream_candidates: list[Any] = []
    to_unicode = font.get(NameObject("/ToUnicode"))
    if to_unicode is not None:
        stream_candidates.append(to_unicode)
    for font_dictionary in font_dictionaries:
        if not isinstance(font_dictionary, DictionaryObject):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF descendant Font is invalid.")
        descriptor = font_dictionary.get(NameObject("/FontDescriptor"))
        if isinstance(descriptor, IndirectObject):
            descriptor = descriptor.get_object()
        if descriptor is None:
            continue
        if not isinstance(descriptor, DictionaryObject):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF FontDescriptor is invalid.")
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            candidate = descriptor.get(NameObject(key))
            if candidate is not None:
                stream_candidates.append(candidate)

    for candidate in stream_candidates:
        if isinstance(candidate, IndirectObject):
            identity: tuple[int, int] | int = (candidate.idnum, candidate.generation)
            stream = candidate.get_object()
        else:
            identity = id(candidate)
            stream = candidate
        if identity in seen_streams:
            continue
        seen_streams.add(identity)
        remaining, _decoded = _charge_bounded_content_stream(stream, remaining)
    return remaining


def _validate_form_do_work(
    content_streams: list[bytes],
    resources: Any,
    form_lookup: dict[tuple[int, str], tuple[tuple[int, int] | int, bytes, Any | None]],
) -> None:
    from pypdf.generic import IndirectObject

    if isinstance(resources, IndirectObject):
        resources = resources.get_object()
    invocation_count = 0

    def visit(
        streams: list[bytes],
        current_resources: Any,
        depth: int,
        stack: set[tuple[int, int] | int],
    ) -> None:
        nonlocal invocation_count
        resources_identity = id(current_resources)
        for content in streams:
            for form_name in _form_do_names(content):
                form = form_lookup.get((resources_identity, form_name))
                if form is None:
                    continue
                identity, form_content, nested_resources = form
                invocation_count += 1
                if (
                    invocation_count > _MAX_FORM_DO_INVOCATIONS
                    or depth + 1 > _MAX_FORM_XOBJECT_DEPTH
                ):
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF Form XObject invocation work exceeds safety limits.",
                    )
                if identity in stack or nested_resources is None:
                    continue
                resolved_nested = (
                    nested_resources.get_object()
                    if isinstance(nested_resources, IndirectObject)
                    else nested_resources
                )
                visit([form_content], resolved_nested, depth + 1, stack | {identity})

    visit(content_streams, resources, 0, set())


def _form_do_names(content: bytes) -> tuple[str, ...]:
    from pypdf.generic import ContentStream, DecodedStreamObject, NameObject

    stream = DecodedStreamObject()
    stream.set_data(content)
    operations = ContentStream(stream, None).operations
    if len(operations) > _MAX_CONTENT_OPERATIONS:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF content operation count exceeds safety limits.",
        )
    names: list[str] = []
    for operands, operator in operations:
        if operator != b"Do":
            continue
        if not operands or not isinstance(operands[0], NameObject):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF Do operation is invalid.")
        names.append(str(operands[0]))
    return tuple(names)


def _bounded_flate_decoded_data(data: bytes, remaining: int) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(data, remaining + 1)
        if len(decoded) > remaining or decompressor.unconsumed_tail or not decompressor.eof:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF decoded page content exceeds safety limits.",
            )
        return decoded
    except ProofAgentError:
        raise
    except zlib.error as exc:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF compressed page content is invalid.",
        ) from exc


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
    revisions = _structural_revisions_before(source, before)
    return revisions[-1] if revisions else None


def _structural_revisions_before(source: IO[bytes], before: int) -> list[tuple[int, int]]:
    eof_offsets = _marker_offsets(source, b"%%EOF", before=before)
    startxref_offsets = _marker_offsets(source, b"startxref", before=before)
    revisions: list[tuple[int, int]] = []
    for eof_offset in eof_offsets:
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
                xref_offset = int(match.group("offset"))
                if not _is_structural_xref_candidate(
                    source,
                    xref_offset=xref_offset,
                    startxref_offset=previous_startxref,
                ):
                    continue
                revisions.append((eof_end, xref_offset))
                break
    return revisions


def _is_structural_xref_candidate(
    source: IO[bytes],
    *,
    xref_offset: int,
    startxref_offset: int,
) -> bool:
    structure_size = startxref_offset - xref_offset
    if xref_offset <= 0 or structure_size <= 0 or structure_size > _PDF_REVISION_STRUCTURE_BYTES:
        return False
    source.seek(xref_offset)
    structure = source.read(structure_size)
    if structure.startswith(b"xref"):
        return re.search(rb"\btrailer\b", structure) is not None
    return (
        re.match(
            rb"[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+[0-9]+[\x00\x09\x0a\x0c\x0d\x20]+obj\b",
            structure,
        )
        is not None
        and re.search(rb"/Type[\x00\x09\x0a\x0c\x0d\x20]+/XRef\b", structure) is not None
    )


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
                if len(offsets) > _MAX_REVISION_MARKER_CANDIDATES:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF revision marker count exceeds safety limits.",
                    )
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
    prefix_start_bytes = source.read(min(prefix_size, _PDF_BOUNDARY_SCAN_BYTES))
    prefix_start = _strip_leading_pdf_trivia(prefix_start_bytes)
    if prefix_start is None or (not prefix_start and prefix_size > len(prefix_start_bytes)):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental boundary is invalid.")
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
    prefix_end_start = max(previous_eof_end, xref_offset - _PDF_BOUNDARY_SCAN_BYTES)
    source.seek(prefix_end_start)
    prefix_end = _strip_trailing_pdf_trivia(source.read(xref_offset - prefix_end_start))
    if prefix_end is None or not prefix_end.endswith(b"endobj"):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF incremental objects are invalid.")


def _strip_leading_pdf_trivia(value: bytes) -> bytes | None:
    position = 0
    while position < len(value):
        while position < len(value) and value[position] in _PDF_WHITESPACE:
            position += 1
        if position >= len(value) or value[position] != ord("%"):
            return value[position:]
        newline = min(
            (
                index
                for index in (value.find(b"\n", position), value.find(b"\r", position))
                if index >= 0
            ),
            default=-1,
        )
        if newline < 0:
            return None
        position = newline + 1
    return b""


def _strip_trailing_pdf_trivia(value: bytes) -> bytes | None:
    endobj_end = value.rfind(b"endobj")
    if endobj_end < 0:
        return None
    endobj_end += len(b"endobj")
    if not _is_pdf_trivia(value[endobj_end:]):
        return None
    return value[:endobj_end]


def _is_pdf_trivia(value: bytes) -> bool:
    position = 0
    while position < len(value):
        while position < len(value) and value[position] in _PDF_WHITESPACE:
            position += 1
        if position >= len(value):
            return True
        if value[position] != ord("%"):
            return False
        newline = min(
            (
                index
                for index in (value.find(b"\n", position), value.find(b"\r", position))
                if index >= 0
            ),
            default=-1,
        )
        if newline < 0:
            return False
        position = newline + 1
    return True


def _reject_unsafe_pdf_objects(reader: Any) -> None:
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    pending: list[tuple[Any, str | None]] = [
        (reader.trailer, None),
        *((item, None) for item in _indexed_pdf_objects(reader)),
    ]
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


def _indexed_pdf_objects(reader: Any) -> tuple[Any, ...]:
    """Return every object registered by the complete parsed xref revision chain."""

    from pypdf.generic import IndirectObject

    references: set[tuple[int, int]] = set()
    for generation, entries in reader.xref.items():
        references.update((int(idnum), int(generation)) for idnum in entries if int(idnum) > 0)
    references.update((int(idnum), 0) for idnum in reader.xref_objStm if int(idnum) > 0)
    if len(references) > _MAX_INDEXED_PDF_OBJECTS:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF indexed object count exceeds safety limits.",
        )

    indexed: list[Any] = [
        IndirectObject(idnum, generation, reader)
        for idnum, generation in sorted(references, key=lambda item: (item[1], item[0]))
    ]
    for resolved in reader.resolved_objects.values():
        indexed.append(resolved)
        if len(indexed) > _MAX_INDEXED_PDF_OBJECTS:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF indexed object count exceeds safety limits.",
            )
    return tuple(indexed)


def _reject_unsafe_historical_revisions(source: IO[bytes], reader_type: Any) -> None:
    source.seek(0, os.SEEK_END)
    revisions = _structural_revisions_before(source, source.tell())
    if len(revisions) > _MAX_PDF_REVISIONS:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF revision count exceeds safety limits.",
        )

    historical_bytes = 0
    for eof_end, _xref_offset in revisions[:-1]:
        historical_bytes += eof_end
        if historical_bytes > _MAX_HISTORICAL_REVISION_BYTES:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF historical revision scan exceeds safety limits.",
            )
        historical: IO[bytes] = tempfile.SpooledTemporaryFile(
            max_size=_SNAPSHOT_MEMORY_BYTES,
            mode="w+b",
        )
        try:
            source.seek(0)
            remaining = eof_end
            while remaining > 0:
                chunk = source.read(min(_HASH_CHUNK_BYTES, remaining))
                if not chunk:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF historical revision is incomplete.",
                    )
                historical.write(chunk)
                remaining -= len(chunk)
            historical.seek(0)
            historical_reader = reader_type(historical, strict=True)
            _reject_unsafe_pdf_objects(historical_reader)
        finally:
            historical.close()


def _hybrid_error(code: str, message: str) -> ProofAgentError:
    return ProofAgentError(code, message, _FIX)
