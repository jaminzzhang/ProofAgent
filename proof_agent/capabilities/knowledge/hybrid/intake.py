"""Safe, content-free PDF preflight for Hybrid Index intake."""

from __future__ import annotations

import base64
import binascii
import hashlib
from importlib import import_module
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
_MAX_STRUCTURAL_STREAM_DECODED_BYTES = 2 * 1024 * 1024
_MAX_STRUCTURAL_STREAM_DICTIONARY_BYTES = 64 * 1024
_MAX_STRUCTURAL_STREAM_CANDIDATES = 256
_MAX_RAW_PDF_TOKENS = 500_000
_MAX_SIMPLE_INDIRECT_OBJECTS = 10_000
_MAX_INDIRECT_OBJECTS = 100_000
_MAX_SIMPLE_INDIRECT_VALUE_TOKENS = 1_024
_MAX_STRUCTURAL_DICTIONARY_TOKENS = 10_000
_MAX_FORM_XOBJECT_DEPTH = 16
_MAX_FORM_XOBJECTS = 256
_MAX_FORM_DO_INVOCATIONS = 64
_MAX_XOBJECT_RESOURCE_ENTRIES = 1024
_MAX_FONT_RESOURCE_ENTRIES = 1024
_MAX_CONTENT_OPERATIONS = 100_000
_MAX_CONTENT_TOKENS = 100_000
_MAX_DESCENDANT_FONT_ENTRIES = 256
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
        revision_boundaries = _validate_terminal_pdf_region(snapshot)
        authoritative_offsets = _validated_xref_object_offsets(
            snapshot, revision_boundaries=revision_boundaries
        )
        _validate_bounded_structural_streams(
            snapshot,
            revision_boundaries=revision_boundaries,
            authoritative_object_offsets=authoritative_offsets,
        )
        snapshot.seek(0)
        reader = PdfReader(snapshot, strict=True)
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
    from pypdf.generic import ArrayObject, IndirectObject, NameObject, NullObject, StreamObject

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
        filter_values = tuple(filters) if isinstance(filters, ArrayObject) else (filters,)
        decode_parms = stream.get(NameObject("/DecodeParms"))
        if isinstance(decode_parms, IndirectObject):
            decode_parms = decode_parms.get_object()
        parm_values = (
            tuple(decode_parms)
            if isinstance(decode_parms, ArrayObject)
            else tuple(decode_parms for _ in filter_values)
        )
        decoded = raw_data
        for index, filter_value in enumerate(filter_values):
            parms = parm_values[index] if index < len(parm_values) else None
            if isinstance(parms, IndirectObject):
                parms = parms.get_object()
            if isinstance(parms, NullObject):
                parms = None
            decoded = _decode_bounded_standard_filter(
                decoded,
                str(filter_value),
                parms,
                remaining,
            )
    remaining -= len(decoded)
    if remaining < 0:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF decoded page content exceeds safety limits.",
        )
    return remaining, decoded


def _decode_bounded_standard_filter(
    data: bytes,
    filter_name: str,
    decode_parms: Any,
    remaining: int,
) -> bytes:
    if filter_name in {"/FlateDecode", "/Fl"}:
        return _apply_bounded_predictor(
            _bounded_flate_decoded_data(data, remaining), decode_parms, remaining
        )
    if filter_name in {"/ASCII85Decode", "/A85"}:
        clean = b"".join(data.split())
        body = clean[2:-2] if clean.startswith(b"<~") and clean.endswith(b"~>") else clean
        z_count = body.count(b"z")
        ordinary_count = len(body) - z_count
        maximum_decoded = z_count * 4 + (ordinary_count // 5) * 4 + max(0, ordinary_count % 5 - 1)
        if maximum_decoded > remaining:
            raise _decoded_content_limit()
        try:
            decoded = base64.a85decode(clean, adobe=clean.startswith(b"<~"))
        except ValueError as exc:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF ASCII85 content is invalid."
            ) from exc
        return _require_decoded_limit(decoded, remaining)
    if filter_name in {"/ASCIIHexDecode", "/AHx"}:
        clean = b"".join(data.partition(b">")[0].split())
        if len(clean) % 2:
            clean += b"0"
        if len(clean) // 2 > remaining:
            raise _decoded_content_limit()
        try:
            return _require_decoded_limit(binascii.unhexlify(clean), remaining)
        except (binascii.Error, ValueError) as exc:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF ASCIIHex content is invalid."
            ) from exc
    if filter_name in {"/RunLengthDecode", "/RL"}:
        return _bounded_run_length_decode(data, remaining)
    if filter_name in {"/LZWDecode", "/LZW"}:
        try:
            codec_type = getattr(import_module("pypdf.filters"), "_LzwCodec")
            decoded = codec_type(max_output_length=remaining + 1).decode(data)
        except Exception as exc:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF LZW content is invalid or exceeds limits."
            ) from exc
        return _apply_bounded_predictor(
            _require_decoded_limit(decoded, remaining), decode_parms, remaining
        )
    raise _hybrid_error(
        "PA_HYBRID_INTAKE_006",
        "Hybrid PDF page content filter cannot be sampled safely.",
    )


def _bounded_run_length_decode(data: bytes, remaining: int) -> bytes:
    output = bytearray()
    position = 0
    while position < len(data):
        length = data[position]
        position += 1
        if length == 128:
            return bytes(output)
        if length < 128:
            count = length + 1
            if position + count > len(data):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF RunLength content is invalid."
                )
            if len(output) + count > remaining:
                raise _decoded_content_limit()
            output.extend(data[position : position + count])
            position += count
        else:
            count = 257 - length
            if position >= len(data):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF RunLength content is invalid."
                )
            if len(output) + count > remaining:
                raise _decoded_content_limit()
            output.extend(bytes((data[position],)) * count)
            position += 1
    raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF RunLength content has no EOD.")


def _apply_bounded_predictor(data: bytes, decode_parms: Any, remaining: int) -> bytes:
    if not decode_parms or int(decode_parms.get("/Predictor", 1)) == 1:
        return data
    try:
        from pypdf.filters import FlateDecode
        from pypdf.generic import DictionaryObject, NameObject, NumberObject

        if isinstance(decode_parms, dict) and not isinstance(decode_parms, DictionaryObject):
            decode_parms = DictionaryObject(
                {NameObject(key): NumberObject(value) for key, value in decode_parms.items()}
            )

        predicted = FlateDecode.decode(zlib.compress(data), decode_parms)
    except Exception as exc:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF predictor parameters are invalid."
        ) from exc
    return _require_decoded_limit(predicted, remaining)


def _require_decoded_limit(data: bytes, remaining: int) -> bytes:
    if len(data) > remaining:
        raise _decoded_content_limit()
    return data


def _decoded_content_limit() -> ProofAgentError:
    return _hybrid_error(
        "PA_HYBRID_INTAKE_006",
        "Hybrid PDF decoded page content exceeds safety limits.",
    )


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
    seen_font_dictionaries: set[tuple[int, int] | int] = {id(font)}
    descendants = font.get(NameObject("/DescendantFonts"))
    if isinstance(descendants, IndirectObject):
        descendants = descendants.get_object()
    if isinstance(descendants, ArrayObject):
        if len(descendants) > _MAX_DESCENDANT_FONT_ENTRIES:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF descendant Font count exceeds safety limits.",
            )
        for item in descendants:
            if isinstance(item, IndirectObject):
                descendant_identity: tuple[int, int] | int = (item.idnum, item.generation)
                if descendant_identity in seen_font_dictionaries:
                    continue
                seen_font_dictionaries.add(descendant_identity)
                descendant = item.get_object()
            else:
                descendant_identity = id(item)
                if descendant_identity in seen_font_dictionaries:
                    continue
                seen_font_dictionaries.add(descendant_identity)
                descendant = item
            font_dictionaries.append(descendant)

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

    _preflight_pdf_content_tokens(content)
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


def _preflight_pdf_content_tokens(content: bytes) -> None:
    position = 0
    token_count = 0
    delimiters = b"()<>[]{}/%"
    while position < len(content):
        byte = content[position]
        if byte in _PDF_WHITESPACE:
            position += 1
            continue
        if byte == ord("%"):
            position += 1
            while position < len(content) and content[position] not in b"\r\n":
                position += 1
            continue

        token_count += 1
        if token_count > _MAX_CONTENT_TOKENS:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006",
                "Hybrid PDF content token count exceeds safety limits.",
            )
        if byte == ord("("):
            position = _skip_pdf_literal_string(content, position + 1)
        elif byte == ord("<") and position + 1 < len(content) and content[position + 1] == ord("<"):
            position += 2
        elif byte == ord("<"):
            closing = content.find(b">", position + 1)
            if closing < 0:
                raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF hex string is invalid.")
            position = closing + 1
        elif byte in b">[]{}":
            position += (
                2
                if byte == ord(">")
                and position + 1 < len(content)
                and content[position + 1] == ord(">")
                else 1
            )
        else:
            position += 1
            while (
                position < len(content)
                and content[position] not in _PDF_WHITESPACE
                and content[position] not in delimiters
            ):
                position += 1


def _skip_pdf_literal_string(content: bytes, position: int) -> int:
    depth = 1
    while position < len(content):
        byte = content[position]
        if byte == ord("\\"):
            position += 2
            continue
        if byte == ord("("):
            depth += 1
        elif byte == ord(")"):
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF literal string is invalid.")


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


def _validate_bounded_structural_streams(
    source: IO[bytes],
    *,
    revision_boundaries: tuple[int, ...] = (),
    authoritative_object_offsets: tuple[int, ...] = (),
) -> None:
    source.seek(0)
    raw = source.read()
    simple_objects = _collect_simple_indirect_pdf_values(
        raw,
        revision_boundaries=revision_boundaries,
        authoritative_object_offsets=authoritative_object_offsets,
    )
    position = 0
    token_count = 0
    recent: list[bytes] = []
    in_object = False
    dictionary_depth = 0
    dictionary_tokens: list[tuple[bytes, int]] | None = None
    dictionary_start: int | None = None
    completed_dictionary: list[tuple[bytes, int]] | None = None
    structural_count = 0
    while True:
        token_result = _next_raw_pdf_token(raw, position)
        if token_result is None:
            return
        token, _start, end = token_result
        token_count += 1
        if token_count > _MAX_RAW_PDF_TOKENS:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF raw token count exceeds safety limits."
            )
        position = end
        if token == b"obj" and len(recent) >= 2 and all(value.isdigit() for value in recent[-2:]):
            in_object = True
            completed_dictionary = None
        elif in_object and token == b"<<":
            if dictionary_depth == 0:
                dictionary_tokens = []
                dictionary_start = _start
            if dictionary_tokens is not None:
                _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
                dictionary_tokens.append((token, dictionary_depth))
            dictionary_depth += 1
        elif in_object and token == b">>" and dictionary_depth > 0:
            dictionary_depth -= 1
            if dictionary_tokens is not None:
                _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
                dictionary_tokens.append((token, dictionary_depth))
            if dictionary_depth == 0:
                completed_dictionary = dictionary_tokens
                dictionary_tokens = None
                dictionary_start = None
        elif dictionary_depth > 0 and dictionary_tokens is not None:
            _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
            dictionary_tokens.append((token, dictionary_depth))
        if in_object and token == b"stream" and completed_dictionary is not None:
            length = _structural_dictionary_length(completed_dictionary, simple_objects)
            data_start = _raw_stream_data_start(raw, end)
            data_end = data_start + length
            if data_end > len(raw):
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF structural stream is truncated."
                )
            structural_type = _top_dictionary_name(completed_dictionary, b"/Type", simple_objects)
            if structural_type in {b"/ObjStm", b"/XRef"}:
                structural_count += 1
                if structural_count > _MAX_STRUCTURAL_STREAM_CANDIDATES:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF structural stream candidate count exceeds safety limits.",
                    )
                decoded = raw[data_start:data_end]
                for filter_name in _structural_dictionary_filters(
                    completed_dictionary, simple_objects
                ):
                    decoded = _decode_bounded_standard_filter(
                        decoded,
                        filter_name,
                        None,
                        _MAX_STRUCTURAL_STREAM_DECODED_BYTES,
                    )
                _require_decoded_limit(decoded, _MAX_STRUCTURAL_STREAM_DECODED_BYTES)
            position = data_end
            completed_dictionary = None
        elif token == b"endobj":
            in_object = False
            completed_dictionary = None
        recent.append(token)
        if len(recent) > 3:
            del recent[0]


def _next_raw_pdf_token(raw: bytes, position: int) -> tuple[bytes, int, int] | None:
    while True:
        while position < len(raw) and raw[position] in _PDF_WHITESPACE:
            position += 1
        if position >= len(raw):
            return None
        if raw[position] != ord("%"):
            break
        newline = min(
            (
                index
                for index in (raw.find(b"\n", position), raw.find(b"\r", position))
                if index >= 0
            ),
            default=len(raw) - 1,
        )
        position = newline + 1
    start = position
    if raw.startswith(b"<<", position) or raw.startswith(b">>", position):
        return raw[position : position + 2], start, position + 2
    if raw[position] == ord("("):
        return b"(string)", start, _skip_pdf_literal_string(raw, position + 1)
    if raw[position] == ord("<"):
        closing = raw.find(b">", position + 1)
        if closing < 0:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF hex string is invalid.")
        return b"<hex>", start, closing + 1
    if raw[position] in b"[]{}":
        return raw[position : position + 1], start, position + 1
    position += 1
    while (
        position < len(raw)
        and raw[position] not in _PDF_WHITESPACE
        and raw[position] not in b"()<>[]{}/%"
    ):
        position += 1
    if raw[start] == ord("/"):
        while (
            position < len(raw)
            and raw[position] not in _PDF_WHITESPACE
            and raw[position] not in b"()<>[]{}/%"
        ):
            position += 1
    return raw[start:position], start, position


def _collect_simple_indirect_pdf_values(
    raw: bytes,
    *,
    revision_boundaries: tuple[int, ...] = (),
    authoritative_object_offsets: tuple[int, ...] = (),
) -> dict[tuple[int, int], tuple[bytes, ...]]:
    authoritative_values = _simple_indirect_values_at_offsets(raw, authoritative_object_offsets)
    values: dict[tuple[int, int], tuple[bytes, ...]] = {}
    seen_identities: set[tuple[int, int]] = set()
    last_identity_revision: dict[tuple[int, int], int] = {}
    position = 0
    token_count = 0
    recent: list[bytes] = []
    current_identity: tuple[int, int] | None = None
    current_value: list[bytes] = []
    simple_candidate = False
    dictionary_depth = 0
    dictionary_tokens: list[tuple[bytes, int]] | None = None
    dictionary_start: int | None = None
    completed_dictionary: list[tuple[bytes, int]] | None = None
    while True:
        result = _next_raw_pdf_token(raw, position)
        if result is None:
            break
        token, _start, end = result
        position = end
        token_count += 1
        if token_count > _MAX_RAW_PDF_TOKENS:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF raw token count exceeds safety limits."
            )
        if (
            current_identity is None
            and token == b"obj"
            and len(recent) >= 2
            and all(value.isdigit() for value in recent[-2:])
        ):
            current_identity = (int(recent[-2]), int(recent[-1]))
            current_revision = sum(boundary <= _start for boundary in revision_boundaries)
            previous_revision = last_identity_revision.get(current_identity)
            if previous_revision is not None and current_revision <= previous_revision:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF contains duplicate indirect objects."
                )
            if current_identity not in seen_identities:
                if len(seen_identities) >= _MAX_INDIRECT_OBJECTS:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF indirect object count exceeds safety limits.",
                    )
                seen_identities.add(current_identity)
            last_identity_revision[current_identity] = current_revision
            current_value = []
            simple_candidate = True
            completed_dictionary = None
        elif current_identity is not None and token == b"<<":
            simple_candidate = False
            if dictionary_depth == 0:
                dictionary_tokens = []
                dictionary_start = _start
            if dictionary_tokens is not None:
                _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
                dictionary_tokens.append((token, dictionary_depth))
            dictionary_depth += 1
        elif current_identity is not None and token == b">>" and dictionary_depth > 0:
            dictionary_depth -= 1
            if dictionary_tokens is not None:
                _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
                dictionary_tokens.append((token, dictionary_depth))
            if dictionary_depth == 0:
                completed_dictionary = dictionary_tokens
                dictionary_tokens = None
                dictionary_start = None
        elif dictionary_depth > 0 and dictionary_tokens is not None:
            _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, end)
            dictionary_tokens.append((token, dictionary_depth))
        elif token == b"stream" and current_identity is not None:
            if completed_dictionary is None:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF stream dictionary is invalid."
                )
            resolvable_values = dict(values)
            resolvable_values.update(authoritative_values)
            length = _structural_dictionary_length(completed_dictionary, resolvable_values)
            data_start = _raw_stream_data_start(raw, end)
            position = data_start + length
            if position > len(raw):
                raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF stream is truncated.")
            current_value = []
            simple_candidate = False
            recent.clear()
        elif token == b"endobj" and current_identity is not None:
            if simple_candidate and _is_simple_indirect_value(current_value):
                if current_identity not in values and len(values) >= _MAX_SIMPLE_INDIRECT_OBJECTS:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006",
                        "Hybrid PDF simple indirect object count exceeds safety limits.",
                    )
                values[current_identity] = tuple(current_value)
            current_identity = None
            current_value = []
            simple_candidate = False
            dictionary_depth = 0
            dictionary_tokens = None
            dictionary_start = None
            completed_dictionary = None
        elif current_identity is not None and dictionary_depth == 0 and simple_candidate:
            if len(current_value) >= _MAX_SIMPLE_INDIRECT_VALUE_TOKENS:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006",
                    "Hybrid PDF simple indirect object exceeds safety limits.",
                )
            current_value.append(token)
        recent.append(token)
        if len(recent) > 3:
            del recent[0]
    return values


def _simple_indirect_values_at_offsets(
    raw: bytes, offsets: tuple[int, ...]
) -> dict[tuple[int, int], tuple[bytes, ...]]:
    values: dict[tuple[int, int], tuple[bytes, ...]] = {}
    for offset in sorted(set(offsets)):
        position = offset
        header: list[bytes] = []
        for _ in range(3):
            result = _next_raw_pdf_token(raw, position)
            if result is None:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object offset is invalid."
                )
            token, _start, position = result
            header.append(token)
        if not (header[0].isdigit() and header[1].isdigit() and header[2] == b"obj"):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref object offset is invalid.")
        identity = (int(header[0]), int(header[1]))
        object_tokens: list[bytes] = []
        for _ in range(_MAX_SIMPLE_INDIRECT_VALUE_TOKENS + 1):
            result = _next_raw_pdf_token(raw, position)
            if result is None:
                break
            token, _start, position = result
            if token in {b"<<", b"stream"}:
                break
            if token == b"endobj":
                if _is_simple_indirect_value(object_tokens):
                    if identity not in values and len(values) >= _MAX_SIMPLE_INDIRECT_OBJECTS:
                        raise _hybrid_error(
                            "PA_HYBRID_INTAKE_006",
                            "Hybrid PDF simple indirect object count exceeds safety limits.",
                        )
                    values[identity] = tuple(object_tokens)
                break
            if len(object_tokens) >= _MAX_SIMPLE_INDIRECT_VALUE_TOKENS:
                raise _hybrid_error(
                    "PA_HYBRID_INTAKE_006",
                    "Hybrid PDF simple indirect object exceeds safety limits.",
                )
            object_tokens.append(token)
    return values


def _require_dictionary_token_capacity(
    tokens: list[tuple[bytes, int]], dictionary_start: int | None, token_end: int
) -> None:
    if (
        len(tokens) >= _MAX_STRUCTURAL_DICTIONARY_TOKENS
        or dictionary_start is None
        or token_end - dictionary_start > _MAX_STRUCTURAL_STREAM_DICTIONARY_BYTES
    ):
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF stream dictionary exceeds safety limits."
        )


def _is_simple_indirect_value(tokens: list[bytes]) -> bool:
    if len(tokens) == 1:
        return tokens[0].isdigit() or tokens[0].startswith(b"/")
    return (
        len(tokens) >= 2
        and tokens[0] == b"["
        and tokens[-1] == b"]"
        and all(token.startswith(b"/") for token in tokens[1:-1])
    )


def _top_dictionary_value(tokens: list[tuple[bytes, int]], key: bytes) -> tuple[bytes, ...] | None:
    for index, (token, depth) in enumerate(tokens):
        if (
            not token.startswith(b"/")
            or _normalize_pdf_name(token) != key
            or depth != 1
            or index + 1 >= len(tokens)
        ):
            continue
        values = [tokens[index + 1][0]]
        if values[0] == b"[":
            cursor = index + 2
            while cursor < len(tokens) and tokens[cursor][0] != b"]":
                values.append(tokens[cursor][0])
                cursor += 1
            values.append(b"]")
        elif index + 3 < len(tokens) and tokens[index + 3][0] == b"R":
            values.extend((tokens[index + 2][0], tokens[index + 3][0]))
        return tuple(values)
    return None


def _top_dictionary_name(
    tokens: list[tuple[bytes, int]],
    key: bytes,
    simple_objects: dict[tuple[int, int], tuple[bytes, ...]],
) -> bytes | None:
    value = _top_dictionary_value(tokens, key)
    if value and len(value) == 3 and value[0].isdigit() and value[1].isdigit() and value[2] == b"R":
        value = simple_objects.get((int(value[0]), int(value[1])))
        if value is None:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF structural Type cannot be resolved safely."
            )
    if value is None:
        return None
    if len(value) != 1 or not value[0].startswith(b"/"):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF structural Type is invalid.")
    return _normalize_pdf_name(value[0])


def _normalize_pdf_name(token: bytes) -> bytes:
    if not token.startswith(b"/"):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF name is invalid.")
    normalized = bytearray(b"/")
    index = 1
    while index < len(token):
        if token[index] != ord("#"):
            normalized.append(token[index])
            index += 1
            continue
        if index + 2 >= len(token):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF name escape is invalid.")
        escaped = token[index + 1 : index + 3]
        try:
            normalized.append(int(escaped, 16))
        except ValueError as exc:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF name escape is invalid."
            ) from exc
        index += 3
    return bytes(normalized)


def _structural_dictionary_length(
    tokens: list[tuple[bytes, int]],
    simple_objects: dict[tuple[int, int], tuple[bytes, ...]],
) -> int:
    value = _top_dictionary_value(tokens, b"/Length")
    if value and len(value) == 1 and value[0].isdigit():
        return int(value[0])
    if value and len(value) == 3 and value[0].isdigit() and value[1].isdigit() and value[2] == b"R":
        resolved = simple_objects.get((int(value[0]), int(value[1])))
        if resolved and len(resolved) == 1 and resolved[0].isdigit():
            return int(resolved[0])
    raise _hybrid_error(
        "PA_HYBRID_INTAKE_006", "Hybrid PDF stream length cannot be bounded safely."
    )


def _structural_dictionary_filters(
    tokens: list[tuple[bytes, int]],
    simple_objects: dict[tuple[int, int], tuple[bytes, ...]],
) -> tuple[str, ...]:
    value = _top_dictionary_value(tokens, b"/Filter")
    if value is None:
        return ()
    if len(value) == 3 and value[0].isdigit() and value[1].isdigit() and value[2] == b"R":
        value = simple_objects.get((int(value[0]), int(value[1])))
        if value is None:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF structural Filter cannot be resolved safely."
            )
    name_tokens = tuple(_normalize_pdf_name(token) for token in value if token.startswith(b"/"))
    if not name_tokens or any(
        not token.startswith(b"/") for token in value if token not in {b"[", b"]"}
    ):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF structural Filter is invalid.")
    try:
        return tuple(token.decode("ascii") for token in name_tokens)
    except UnicodeDecodeError as exc:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF structural Filter is invalid."
        ) from exc


def _raw_stream_data_start(raw: bytes, stream_token_end: int) -> int:
    if raw[stream_token_end : stream_token_end + 2] == b"\r\n":
        return stream_token_end + 2
    if raw[stream_token_end : stream_token_end + 1] in {b"\r", b"\n"}:
        return stream_token_end + 1
    raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF stream boundary is invalid.")


def _validate_terminal_pdf_region(source: IO[bytes]) -> tuple[int, ...]:
    startxref_offset = _last_marker_offset(source, b"startxref")
    if startxref_offset is None:
        return ()
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
    reverse_boundaries: list[int] = []
    current_xref_offset = xref_offset
    current_startxref_offset = startxref_offset
    while True:
        previous_revision = _previous_revision_before(source, current_startxref_offset)
        if previous_revision is None:
            return tuple(reversed(reverse_boundaries))
        previous_eof_end, previous_xref_offset = previous_revision
        if current_xref_offset <= previous_eof_end:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_009",
                "Hybrid PDF upload contains bytes outside a valid incremental revision.",
            )
        _validate_incremental_revision(
            source,
            previous_eof_end=previous_eof_end,
            previous_xref_offset=previous_xref_offset,
            xref_offset=current_xref_offset,
            startxref_offset=current_startxref_offset,
        )
        reverse_boundaries.append(previous_eof_end)
        previous_startxref_offset = _last_marker_offset(
            source, b"startxref", before=previous_eof_end
        )
        if previous_startxref_offset is None:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF revision chain is invalid.")
        current_xref_offset = previous_xref_offset
        current_startxref_offset = previous_startxref_offset


def _validated_xref_object_offsets(
    source: IO[bytes], *, revision_boundaries: tuple[int, ...]
) -> tuple[int, ...]:
    source.seek(0, os.SEEK_END)
    size = source.tell()
    xref_offsets: list[int] = []
    for revision_end in (*revision_boundaries, size):
        startxref_offset = _last_marker_offset(source, b"startxref", before=revision_end)
        if startxref_offset is None:
            continue
        source.seek(startxref_offset)
        terminal_region = source.read(revision_end - startxref_offset)
        match = _PDF_TERMINAL_REGION.fullmatch(terminal_region)
        if match is None:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF revision boundary is invalid.")
        xref_offsets.append(int(match.group("offset")))
    source.seek(0)
    raw = source.read()
    object_offsets: set[int] = set()
    for xref_offset in xref_offsets:
        if raw.startswith(b"xref", xref_offset):
            object_offsets.update(_classic_xref_object_offsets(raw, xref_offset))
        else:
            object_offsets.update(_xref_stream_object_offsets(raw, xref_offset))
        if len(object_offsets) > _MAX_INDIRECT_OBJECTS:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object count exceeds safety limits."
            )
    return tuple(sorted(object_offsets))


def _classic_xref_object_offsets(raw: bytes, xref_offset: int) -> tuple[int, ...]:
    position = xref_offset
    first = _next_raw_pdf_token(raw, position)
    if first is None or first[0] != b"xref":
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref table is invalid.")
    position = first[2]
    offsets: list[int] = []
    entry_count = 0
    while True:
        subsection = _next_raw_pdf_token(raw, position)
        if subsection is None:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref table is truncated.")
        start_token, _start, position = subsection
        if start_token == b"trailer":
            return tuple(offsets)
        count_result = _next_raw_pdf_token(raw, position)
        if count_result is None or not start_token.isdigit() or not count_result[0].isdigit():
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref table is invalid.")
        count = int(count_result[0])
        position = count_result[2]
        if count > _MAX_INDIRECT_OBJECTS - entry_count:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object count exceeds safety limits."
            )
        entry_count += count
        for _ in range(count):
            fields: list[bytes] = []
            for _field in range(3):
                result = _next_raw_pdf_token(raw, position)
                if result is None:
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006", "Hybrid PDF xref table is truncated."
                    )
                fields.append(result[0])
                position = result[2]
            if not (fields[0].isdigit() and fields[1].isdigit() and fields[2] in {b"n", b"f"}):
                raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref entry is invalid.")
            if fields[2] == b"n":
                offset = int(fields[0])
                if offset <= 0 or offset >= len(raw):
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object offset is invalid."
                    )
                offsets.append(offset)


def _xref_stream_object_offsets(raw: bytes, xref_offset: int) -> tuple[int, ...]:
    position = xref_offset
    for expected in (None, None, b"obj"):
        result = _next_raw_pdf_token(raw, position)
        if result is None or (expected is not None and result[0] != expected):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is invalid.")
        if expected is None and not result[0].isdigit():
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is invalid.")
        position = result[2]
    dictionary_tokens: list[tuple[bytes, int]] = []
    dictionary_start: int | None = None
    depth = 0
    while True:
        result = _next_raw_pdf_token(raw, position)
        if result is None:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is truncated.")
        token, start, position = result
        if token == b"<<":
            if depth == 0:
                dictionary_start = start
            _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, position)
            dictionary_tokens.append((token, depth))
            depth += 1
        elif token == b">>" and depth > 0:
            depth -= 1
            _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, position)
            dictionary_tokens.append((token, depth))
        elif depth > 0:
            _require_dictionary_token_capacity(dictionary_tokens, dictionary_start, position)
            dictionary_tokens.append((token, depth))
        elif token == b"stream" and dictionary_tokens:
            break
        else:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is invalid.")
    length = _structural_dictionary_length(dictionary_tokens, {})
    data_start = _raw_stream_data_start(raw, position)
    data_end = data_start + length
    if data_end > len(raw):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is truncated.")
    decoded = raw[data_start:data_end]
    filters = _structural_dictionary_filters(dictionary_tokens, {})
    decode_parms = _structural_dictionary_decode_parms(dictionary_tokens, len(filters))
    for filter_index, filter_name in enumerate(filters):
        decoded = _decode_bounded_standard_filter(
            decoded,
            filter_name,
            decode_parms[filter_index],
            _MAX_STRUCTURAL_STREAM_DECODED_BYTES,
        )
    widths = _top_dictionary_integer_array(dictionary_tokens, b"/W")
    if len(widths) != 3 or sum(widths) <= 0:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref widths are invalid.")
    index = _top_dictionary_integer_array(dictionary_tokens, b"/Index")
    if not index:
        size_value = _top_dictionary_value(dictionary_tokens, b"/Size")
        if size_value is None or len(size_value) != 1 or not size_value[0].isdigit():
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref size is invalid.")
        index = (0, int(size_value[0]))
    if len(index) % 2 != 0:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref index is invalid.")
    total_entries = sum(index[cursor + 1] for cursor in range(0, len(index), 2))
    if total_entries > _MAX_INDIRECT_OBJECTS:
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object count exceeds safety limits."
        )
    entry_width = sum(widths)
    if len(decoded) < total_entries * entry_width:
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref stream is truncated.")
    offsets: list[int] = []
    data_position = 0
    for cursor in range(0, len(index), 2):
        for _object_id in range(index[cursor], index[cursor] + index[cursor + 1]):
            fields: list[int] = []
            for field_index, width in enumerate(widths):
                field = decoded[data_position : data_position + width]
                data_position += width
                fields.append(
                    (1 if field_index == 0 else 0) if width == 0 else int.from_bytes(field)
                )
            if fields[0] == 1:
                if fields[1] <= 0 or fields[1] >= len(raw):
                    raise _hybrid_error(
                        "PA_HYBRID_INTAKE_006", "Hybrid PDF xref object offset is invalid."
                    )
                offsets.append(fields[1])
    return tuple(offsets)


def _top_dictionary_integer_array(tokens: list[tuple[bytes, int]], key: bytes) -> tuple[int, ...]:
    value = _top_dictionary_value(tokens, key)
    if value is None:
        return ()
    integers = value[1:-1] if len(value) >= 2 and value[0] == b"[" and value[-1] == b"]" else ()
    if not integers or any(not token.isdigit() for token in integers):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF xref array is invalid.")
    return tuple(int(token) for token in integers)


def _structural_dictionary_decode_parms(
    tokens: list[tuple[bytes, int]], filter_count: int
) -> tuple[dict[str, int] | None, ...]:
    value_index: int | None = None
    for index, (token, depth) in enumerate(tokens):
        if depth == 1 and token.startswith(b"/") and _normalize_pdf_name(token) == b"/DecodeParms":
            value_index = index + 1
            break
    if value_index is None:
        return tuple(None for _ in range(filter_count))
    if value_index >= len(tokens):
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")
    token = tokens[value_index][0]
    if token == b"null":
        return tuple(None for _ in range(filter_count))
    if token == b"<<":
        parms, _next_index = _direct_decode_parms_dictionary(tokens, value_index)
        return tuple(parms for _ in range(filter_count))
    if token != b"[":
        raise _hybrid_error(
            "PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms cannot be resolved safely."
        )
    values: list[dict[str, int] | None] = []
    cursor = value_index + 1
    while cursor < len(tokens) and tokens[cursor][0] != b"]":
        item = tokens[cursor][0]
        if item == b"null":
            values.append(None)
            cursor += 1
        elif item == b"<<":
            parms, cursor = _direct_decode_parms_dictionary(tokens, cursor)
            values.append(parms)
        else:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms cannot be resolved safely."
            )
        if len(values) > filter_count:
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")
    if cursor >= len(tokens) or tokens[cursor][0] != b"]":
        raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")
    values.extend(None for _ in range(filter_count - len(values)))
    return tuple(values)


def _direct_decode_parms_dictionary(
    tokens: list[tuple[bytes, int]], start_index: int
) -> tuple[dict[str, int], int]:
    opening_depth = tokens[start_index][1]
    values: dict[str, int] = {}
    cursor = start_index + 1
    while cursor < len(tokens):
        token, depth = tokens[cursor]
        if token == b">>" and depth == opening_depth:
            return values, cursor + 1
        if depth != opening_depth + 1 or not token.startswith(b"/"):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")
        if cursor + 1 >= len(tokens):
            raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")
        value, value_depth = tokens[cursor + 1]
        if value_depth != opening_depth + 1 or not value.isdigit():
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms cannot be resolved safely."
            )
        try:
            key = _normalize_pdf_name(token).decode("ascii")
        except UnicodeDecodeError as exc:
            raise _hybrid_error(
                "PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid."
            ) from exc
        values[key] = int(value)
        cursor += 2
    raise _hybrid_error("PA_HYBRID_INTAKE_006", "Hybrid PDF DecodeParms is invalid.")


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
