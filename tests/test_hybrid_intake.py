from __future__ import annotations

import base64
import hashlib
from importlib import import_module
from importlib.util import find_spec
import math
from io import BytesIO
import os
from pathlib import Path
import re
from types import ModuleType
from types import SimpleNamespace
import zipfile
import zlib

import pytest
from pydantic import ValidationError

import proof_agent.capabilities.knowledge.hybrid.intake as hybrid_intake_module
from proof_agent.capabilities.knowledge.hybrid import (
    HybridIntakeLimits,
    preflight_hybrid_pdf,
)
from proof_agent.errors import ProofAgentError

pytestmark = pytest.mark.skipif(find_spec("pypdf") is None, reason="pypdf is not installed")


def _modules() -> tuple[ModuleType, ModuleType]:
    return import_module("pypdf"), import_module("pypdf.generic")


def _write_pdf(path: Path, page_texts: tuple[str | None, ...] = (None,)) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        font = generic.DictionaryObject(
            {
                generic.NameObject("/Type"): generic.NameObject("/Font"),
                generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
                generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
            }
        )
        stream = generic.DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[generic.NameObject("/Resources")] = generic.DictionaryObject(
            {
                generic.NameObject("/Font"): generic.DictionaryObject(
                    {generic.NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        page[generic.NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_encrypted_pdf(path: Path) -> Path:
    pypdf, _ = _modules()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("")
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_image_only_pdf(path: Path) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    image = generic.DecodedStreamObject()
    image.set_data(b"\x00\x00\x00")
    image.update(
        {
            generic.NameObject("/Type"): generic.NameObject("/XObject"),
            generic.NameObject("/Subtype"): generic.NameObject("/Image"),
            generic.NameObject("/Width"): generic.NumberObject(1),
            generic.NameObject("/Height"): generic.NumberObject(1),
            generic.NameObject("/ColorSpace"): generic.NameObject("/DeviceRGB"),
            generic.NameObject("/BitsPerComponent"): generic.NumberObject(8),
        }
    )
    content = generic.DecodedStreamObject()
    content.set_data(b"q 100 0 0 100 72 600 cm /Im0 Do Q")
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/XObject"): generic.DictionaryObject(
                {generic.NameObject("/Im0"): writer._add_object(image)}
            )
        }
    )
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_pdf_with_revision_markers_in_content(path: Path) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    content = generic.DecodedStreamObject()
    content.set_data(b"% benign content marker\nstartxref\n0\n%%EOF\n")
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_compressed_content_pdf(path: Path, content_bytes: bytes) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    decoded = generic.DecodedStreamObject()
    decoded.set_data(content_bytes)
    page[generic.NameObject("/Contents")] = writer._add_object(decoded.flate_encode())
    page[generic.NameObject("/Resources")] = generic.DictionaryObject()
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _run_length_encode(data: bytes) -> bytes:
    encoded = bytearray()
    for offset in range(0, len(data), 128):
        chunk = data[offset : offset + 128]
        encoded.append(len(chunk) - 1)
        encoded.extend(chunk)
    encoded.append(128)
    return bytes(encoded)


def _write_standard_filtered_content_pdf(
    path: Path,
    filters: tuple[str, ...],
    content_bytes: bytes = b"% benign standard-filter content\n",
    *,
    null_decode_parms: bool = False,
) -> Path:
    pypdf, generic = _modules()
    encoded = content_bytes
    for filter_name in reversed(filters):
        if filter_name == "/FlateDecode":
            encoded = zlib.compress(encoded)
        elif filter_name == "/ASCII85Decode":
            encoded = base64.a85encode(encoded, adobe=True)
        elif filter_name == "/RunLengthDecode":
            encoded = _run_length_encode(encoded)
        elif filter_name == "/LZWDecode":
            filters_module = import_module("pypdf.filters")
            encoded = filters_module._LzwCodec().encode(encoded)
        else:
            raise AssertionError(filter_name)
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = generic.EncodedStreamObject()
    stream._data = encoded
    stream[generic.NameObject("/Filter")] = (
        generic.ArrayObject([generic.NameObject(value) for value in filters])
        if len(filters) > 1
        else generic.NameObject(filters[0])
    )
    if null_decode_parms:
        stream[generic.NameObject("/DecodeParms")] = generic.ArrayObject(
            [generic.NullObject() for _ in filters]
        )
    page[generic.NameObject("/Contents")] = writer._add_object(stream)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject()
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_png_predictor_content_pdf(path: Path) -> Path:
    pypdf, generic = _modules()
    content = b"% predictor-decoded content\n"
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = generic.EncodedStreamObject()
    stream._data = zlib.compress(b"\x00" + content)
    stream[generic.NameObject("/Filter")] = generic.NameObject("/FlateDecode")
    stream[generic.NameObject("/DecodeParms")] = generic.DictionaryObject(
        {
            generic.NameObject("/Predictor"): generic.NumberObject(12),
            generic.NameObject("/Columns"): generic.NumberObject(len(content)),
            generic.NameObject("/Colors"): generic.NumberObject(1),
            generic.NameObject("/BitsPerComponent"): generic.NumberObject(8),
        }
    )
    page[generic.NameObject("/Contents")] = writer._add_object(stream)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject()
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_object_stream_pdf(
    path: Path,
    *,
    padding_bytes: int,
    nested_dictionary_before_type: bool = False,
    indirect_filter_and_length: bool = False,
    escaped_filter_name: bool = False,
    escaped_object_stream_type: bool = False,
    indirect_object_stream_type: bool = False,
    escaped_xref_type: bool = False,
    xref_padding_bytes: int = 0,
    xref_predictor: bool = False,
) -> Path:
    object_stream_decoded = b"2 0 << /Dummy true >>\n%" + b"A" * padding_bytes
    object_stream_encoded = zlib.compress(object_stream_decoded)
    parts = [b"%PDF-1.5\n"]
    offsets: dict[int, int] = {}

    def add_object(object_id: int, body: bytes) -> None:
        offsets[object_id] = sum(len(part) for part in parts)
        parts.append(f"{object_id} 0 obj\n".encode("ascii") + body + b"\nendobj\n")

    type_value = (
        b"9 0 R"
        if indirect_object_stream_type
        else (b"/Obj#53tm" if escaped_object_stream_type else b"/ObjStm")
    )
    dictionary_prefix = (
        b"<< /DecodeParms << /Predictor 1 >> /Type " + type_value
        if nested_dictionary_before_type
        else b"<< /Type " + type_value
    )
    filter_value = b"7 0 R" if indirect_filter_and_length else b"/FlateDecode"
    if escaped_filter_name and not indirect_filter_and_length:
        filter_value = b"/Flate#44ecode"
    length_value = (
        b"8 0 R" if indirect_filter_and_length else str(len(object_stream_encoded)).encode("ascii")
    )
    if indirect_filter_and_length:
        add_object(7, b"/Flate#44ecode" if escaped_filter_name else b"/FlateDecode")
        add_object(8, str(len(object_stream_encoded)).encode("ascii"))
    if indirect_object_stream_type:
        add_object(9, b"/Obj#53tm" if escaped_object_stream_type else b"/ObjStm")
    add_object(
        1,
        dictionary_prefix
        + b" /N 1 /First 4 /Filter "
        + filter_value
        + b" /Length "
        + length_value
        + b" >>\nstream\n"
        + object_stream_encoded
        + b"\nendstream",
    )
    add_object(3, b"<< /Type /Catalog /Pages 4 0 R >>")
    add_object(4, b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>")
    add_object(
        5,
        b"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 612 792] /Resources << >> >>",
    )
    offsets[6] = sum(len(part) for part in parts)

    def xref_entry(entry_type: int, field2: int, field3: int) -> bytes:
        return bytes((entry_type,)) + field2.to_bytes(4, "big") + field3.to_bytes(2, "big")

    size = 10 if indirect_object_stream_type else (9 if indirect_filter_and_length else 7)
    xref_entries = []
    for object_id in range(size):
        if object_id == 0:
            xref_entries.append(xref_entry(0, 0, 65535))
        elif object_id == 2:
            xref_entries.append(xref_entry(2, 1, 0))
        elif object_id in offsets:
            xref_entries.append(xref_entry(1, offsets[object_id], 0))
        else:
            xref_entries.append(xref_entry(0, 0, 0))
    decoded_xref_data = b"".join(xref_entries) + b"\x00" * xref_padding_bytes
    xref_data = zlib.compress(b"\x00" + decoded_xref_data) if xref_predictor else decoded_xref_data
    xref_filter = (
        b" /Filter /FlateDecode /DecodeParms << /Predictor 12 /Columns "
        + str(len(decoded_xref_data)).encode("ascii")
        + b" >>"
        if xref_predictor
        else b""
    )
    add_object(
        6,
        b"<< /Type "
        + (b"/XR#65f" if escaped_xref_type else b"/XRef")
        + b" /Size "
        + str(size).encode("ascii")
        + b" /Root 3 0 R /W [1 4 2] /Index [0 "
        + str(size).encode("ascii")
        + b"] /Length "
        + str(len(xref_data)).encode("ascii")
        + xref_filter
        + b" >>\nstream\n"
        + xref_data
        + b"\nendstream",
    )
    parts.append(b"startxref\n" + str(offsets[6]).encode("ascii") + b"\n%%EOF\n")
    path.write_bytes(b"".join(parts))
    return path


def test_simple_indirect_resolver_skips_strings_and_length_delimited_streams() -> None:
    fake_objects = b"endstream\n7 0 obj /RunLengthDecode endobj\n8 0 obj 1 endobj"
    raw = (
        b"1 0 obj << /Length "
        + str(len(fake_objects)).encode("ascii")
        + b" >>\nstream\n"
        + fake_objects
        + b"\nendstream\nendobj\n"
        + b"2 0 obj (7 0 obj /ASCIIHexDecode endobj) endobj\n"
        + b"3 0 obj <372030206f626a202f4c5a574465636f646520656e646f626a> endobj\n"
        + b"7 0 obj /FlateDecode endobj\n8 0 obj 123 endobj\n"
    )

    values = hybrid_intake_module._collect_simple_indirect_pdf_values(raw)

    assert values[(7, 0)] == (b"/FlateDecode",)
    assert values[(8, 0)] == (b"123",)


def test_simple_indirect_resolver_rejects_duplicate_object_identity() -> None:
    raw = b"7 0 obj /FlateDecode endobj\n7 0 obj /RunLengthDecode endobj\n"

    with pytest.raises(ProofAgentError) as exc:
        hybrid_intake_module._collect_simple_indirect_pdf_values(raw)

    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_forward_length_uses_xref_offset_without_lexing_stream_body() -> None:
    body = b"endstream\n7 0 obj /RunLengthDecode endobj\n" + b"9 0 obj 1 endobj\n" * 2_000
    parts = [b"%PDF-1.4\n"]
    object_offsets: dict[int, int] = {}

    def add_object(object_id: int, value: bytes) -> None:
        object_offsets[object_id] = sum(len(part) for part in parts)
        parts.append(f"{object_id} 0 obj\n".encode("ascii") + value + b"\nendobj\n")

    add_object(1, b"<< /Length 8 0 R >>\nstream\n" + body + b"\nendstream")
    add_object(8, str(len(body)).encode("ascii"))
    xref_offset = sum(len(part) for part in parts)
    xref_entries = [b"0000000000 65535 f \n"] + [
        (
            f"{object_offsets[object_id]:010d} 00000 n \n".encode("ascii")
            if object_id in object_offsets
            else b"0000000000 00000 f \n"
        )
        for object_id in range(1, 9)
    ]
    parts.extend(
        (
            b"xref\n0 9\n",
            b"".join(xref_entries),
            b"trailer\n<< /Size 9 >>\nstartxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        )
    )
    raw = b"".join(parts)

    source = BytesIO(raw)
    boundaries = hybrid_intake_module._validate_terminal_pdf_region(source)
    offsets = hybrid_intake_module._validated_xref_object_offsets(
        source, revision_boundaries=boundaries
    )
    values = hybrid_intake_module._collect_simple_indirect_pdf_values(
        raw,
        revision_boundaries=boundaries,
        authoritative_object_offsets=offsets,
    )

    assert values[(8, 0)] == (str(len(body)).encode("ascii"),)
    assert (7, 0) not in values
    assert (9, 0) not in values


def test_stream_eof_marker_does_not_authorize_same_revision_duplicate() -> None:
    body = b"benign %%EOF marker"
    raw = (
        b"1 0 obj /Old endobj\n"
        b"2 0 obj << /Length "
        + str(len(body)).encode("ascii")
        + b" >>\nstream\n"
        + body
        + b"\nendstream\nendobj\n1 0 obj /New endobj\n"
    )

    with pytest.raises(ProofAgentError) as exc:
        hybrid_intake_module._collect_simple_indirect_pdf_values(raw)

    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_validated_incremental_boundary_allows_latest_simple_object_value() -> None:
    base_object = b"7 0 obj /Old endobj\n"
    base_xref_offset = len(b"%PDF-1.4\n") + len(base_object)
    base = (
        b"%PDF-1.4\n"
        + base_object
        + b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 8 >>\nstartxref\n"
        + str(base_xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    incremental_object_offset = len(base)
    incremental_object = b"7 0 obj /New endobj\n"
    incremental_xref_offset = incremental_object_offset + len(incremental_object)
    raw = (
        base
        + incremental_object
        + b"xref\n7 1\n"
        + f"{incremental_object_offset:010d} 00000 n \n".encode("ascii")
        + b"trailer\n<< /Size 8 /Prev "
        + str(base_xref_offset).encode("ascii")
        + b" >>\nstartxref\n"
        + str(incremental_xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )

    boundaries = hybrid_intake_module._validate_terminal_pdf_region(BytesIO(raw))
    values = hybrid_intake_module._collect_simple_indirect_pdf_values(
        raw, revision_boundaries=boundaries
    )

    assert boundaries == (base.index(b"%%EOF") + len(b"%%EOF"),)
    assert values[(7, 0)] == (b"/New",)


def test_simple_indirect_resolver_enforces_object_bound_before_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hybrid_intake_module, "_MAX_SIMPLE_INDIRECT_OBJECTS", 2)
    raw = b"1 0 obj 1 endobj\n2 0 obj 2 endobj\n3 0 obj 3 endobj\n"

    with pytest.raises(ProofAgentError) as exc:
        hybrid_intake_module._collect_simple_indirect_pdf_values(raw)

    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_raw_pdf_lexer_skips_long_comment_runs_iteratively() -> None:
    raw = b"% comment\n" * 5_000 + b"1 0 obj 42 endobj\n"

    values = hybrid_intake_module._collect_simple_indirect_pdf_values(raw)

    assert values[(1, 0)] == (b"42",)


@pytest.mark.parametrize(
    ("limit_name", "limit", "dictionary"),
    [
        ("_MAX_STRUCTURAL_DICTIONARY_TOKENS", 3, b"<< /A 1 /B 2 >>"),
        ("_MAX_STRUCTURAL_STREAM_DICTIONARY_BYTES", 16, b"<< /Padding 123456789 >>"),
    ],
)
def test_structural_dictionary_bounds_are_enforced_before_stream_processing(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    dictionary: bytes,
) -> None:
    monkeypatch.setattr(hybrid_intake_module, limit_name, limit)
    raw = b"1 0 obj " + dictionary + b"\nstream\n\nendstream\nendobj\n"

    with pytest.raises(ProofAgentError) as exc:
        hybrid_intake_module._validate_bounded_structural_streams(BytesIO(raw))

    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def _write_nested_form_pdf(
    path: Path,
    form_content: bytes,
    *,
    page_do_count: int = 1,
    escaped_page_form_name: bool = False,
) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    inner_decoded = generic.DecodedStreamObject()
    inner_decoded.set_data(form_content)
    inner = inner_decoded.flate_encode()
    inner.update(
        {
            generic.NameObject("/Type"): generic.NameObject("/XObject"),
            generic.NameObject("/Subtype"): generic.NameObject("/Form"),
            generic.NameObject("/BBox"): generic.ArrayObject(
                [
                    generic.NumberObject(0),
                    generic.NumberObject(0),
                    generic.NumberObject(100),
                    generic.NumberObject(100),
                ]
            ),
            generic.NameObject("/Resources"): generic.DictionaryObject(),
        }
    )
    inner_ref = writer._add_object(inner)

    outer_decoded = generic.DecodedStreamObject()
    outer_decoded.set_data(b"/Inner Do")
    outer = outer_decoded.flate_encode()
    outer.update(
        {
            generic.NameObject("/Type"): generic.NameObject("/XObject"),
            generic.NameObject("/Subtype"): generic.NameObject("/Form"),
            generic.NameObject("/BBox"): generic.ArrayObject(
                [
                    generic.NumberObject(0),
                    generic.NumberObject(0),
                    generic.NumberObject(100),
                    generic.NumberObject(100),
                ]
            ),
            generic.NameObject("/Resources"): generic.DictionaryObject(
                {
                    generic.NameObject("/XObject"): generic.DictionaryObject(
                        {generic.NameObject("/Inner"): inner_ref}
                    )
                }
            ),
        }
    )
    outer_ref = writer._add_object(outer)

    page_content = generic.DecodedStreamObject()
    page_content.set_data(
        (b"/F#31 Do\n" if escaped_page_form_name else b"/Outer Do\n") * page_do_count
    )
    page[generic.NameObject("/Contents")] = writer._add_object(page_content)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/XObject"): generic.DictionaryObject(
                {generic.NameObject("/F1" if escaped_page_form_name else "/Outer"): outer_ref}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_unknown_xobject_pdf(path: Path, subtype: str = "/PS") -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    unknown_decoded = generic.DecodedStreamObject()
    unknown_decoded.set_data(b"compressed provider-specific XObject")
    unknown = unknown_decoded.flate_encode()
    unknown.update(
        {
            generic.NameObject("/Type"): generic.NameObject("/XObject"),
            generic.NameObject("/Subtype"): generic.NameObject(subtype),
        }
    )
    page_content = generic.DecodedStreamObject()
    page_content.set_data(b"/Unknown Do")
    page[generic.NameObject("/Contents")] = writer._add_object(page_content)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/XObject"): generic.DictionaryObject(
                {generic.NameObject("/Unknown"): writer._add_object(unknown)}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_pdf_with_compressed_tounicode(path: Path, cmap_bytes: bytes) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    cmap_decoded = generic.DecodedStreamObject()
    cmap_decoded.set_data(cmap_bytes)
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
            generic.NameObject("/ToUnicode"): writer._add_object(cmap_decoded.flate_encode()),
        }
    )
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/Font"): generic.DictionaryObject(
                {generic.NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_pdf_with_compressed_type1_fontfile(path: Path, font_bytes: bytes) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font_file_decoded = generic.DecodedStreamObject()
    font_file_decoded.set_data(font_bytes)
    descriptor = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/FontDescriptor"),
            generic.NameObject("/FontName"): generic.NameObject("/BoundedType1"),
            generic.NameObject("/FontFile"): writer._add_object(font_file_decoded.flate_encode()),
        }
    )
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/BoundedType1"),
            generic.NameObject("/FontDescriptor"): writer._add_object(descriptor),
        }
    )
    content = generic.DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 72 720 Td (A) Tj ET")
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/Font"): generic.DictionaryObject(
                {generic.NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_pdf_with_many_descendant_fonts(path: Path, count: int) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    descendant = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/CIDFontType2"),
        }
    )
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type0"),
            generic.NameObject("/BaseFont"): generic.NameObject("/BoundedComposite"),
            generic.NameObject("/DescendantFonts"): generic.ArrayObject([descendant] * count),
        }
    )
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/Font"): generic.DictionaryObject(
                {generic.NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_unsafe_pdf(path: Path, *, embedded: bool) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if embedded:
        writer.add_attachment("payload.txt", b"payload")
    else:
        writer._root_object[generic.NameObject("/OpenAction")] = generic.DictionaryObject(
            {
                generic.NameObject("/S"): generic.NameObject("/JavaScript"),
                generic.NameObject("/JS"): generic.TextStringObject("app.alert('x')"),
            }
        )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_action_pdf(path: Path, action_type: str) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer._root_object[generic.NameObject("/A")] = generic.DictionaryObject(
        {
            generic.NameObject("/S"): generic.NameObject(action_type),
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_benign_transparency_pdf(path: Path) -> Path:
    pypdf, generic = _modules()
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[generic.NameObject("/Group")] = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Group"),
            generic.NameObject("/S"): generic.NameObject("/Transparency"),
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_incremental_pdf(path: Path, *, add_unreferenced_embedded_file: bool = False) -> Path:
    pypdf, generic = _modules()
    original = _write_pdf(path)
    writer = pypdf.PdfWriter(original, incremental=True)
    writer.add_metadata({"/Title": "Incrementally updated policy"})
    if add_unreferenced_embedded_file:
        embedded = generic.DecodedStreamObject()
        embedded.set_data(b"MZ\x90\x00executable")
        embedded.update(
            {
                generic.NameObject("/Type"): generic.NameObject("/EmbeddedFile"),
            }
        )
        writer._add_object(embedded)
    updated = path.with_name("incremental-output.pdf")
    with updated.open("wb") as handle:
        writer.write(handle)
    os.replace(updated, path)
    return path


def _write_commented_incremental_pdf(path: Path) -> Path:
    base = _write_pdf(path).read_bytes()
    previous = re.search(rb"startxref\s+(?P<offset>[0-9]+)\s+%%EOF\s*\Z", base)
    assert previous is not None
    leading_comment = b"% before first incremental object\n"
    object_offset = len(base) + len(leading_comment)
    incremental_object = b"5 0 obj\n<< /Label (benign) >>\nendobj"
    trailing_comment = b" % inline after final incremental object\n"
    xref_offset = object_offset + len(incremental_object) + len(trailing_comment)
    revision = (
        leading_comment
        + incremental_object
        + trailing_comment
        + b"xref\n5 1\n"
        + f"{object_offset:010d} 00000 n \n".encode("ascii")
        + b"trailer\n<< /Size 6 /Prev "
        + previous.group("offset")
        + b" >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    path.write_bytes(base + revision)
    return path


def _append_zip_payload(path: Path, *, filename: str, content: bytes) -> Path:
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
        writer.writestr(filename, content)
    with path.open("ab") as handle:
        handle.write(archive.getvalue())
    assert zipfile.is_zipfile(path)
    return path


def test_blank_scanned_pdf_is_accepted_by_hybrid_preflight(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "scan.pdf")
    result = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert result.page_profiles[0].requires_ocr is True


def test_image_only_pdf_is_accepted_and_requires_ocr(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_image_only_pdf(tmp_path / "image.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_profiles[0].requires_ocr is True
    assert result.page_profiles[0].native_extracted_character_count == 0


def test_native_and_mixed_pages_are_profiled_independently(tmp_path: Path) -> None:
    path = _write_pdf(
        tmp_path / "mixed.pdf",
        ("Meaningful native insurance policy text", None),
    )

    result = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())

    assert [profile.page_number for profile in result.page_profiles] == [1, 2]
    assert [profile.requires_ocr for profile in result.page_profiles] == [False, True]
    assert result.page_profiles[0].native_extracted_character_count > 8
    assert result.page_profiles[1].native_text_quality_ratio == 0


def test_preflight_is_deterministic_and_does_not_expose_text(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "native.pdf", ("Meaningful native policy text",))

    first = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    second = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())

    assert first == second
    assert first.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert first.source_size_bytes == path.stat().st_size
    assert "text" not in first.model_dump()
    assert all(math.isfinite(page.native_text_quality_ratio) for page in first.page_profiles)


@pytest.mark.parametrize(
    ("factory", "limits", "code"),
    [
        (
            lambda path: path.write_bytes(b"%PDF-1.7\nnot-a-pdf") or path,
            HybridIntakeLimits(),
            "PA_HYBRID_INTAKE_006",
        ),
        (_write_encrypted_pdf, HybridIntakeLimits(), "PA_HYBRID_INTAKE_003"),
        (_write_pdf, HybridIntakeLimits(max_pdf_pages=1), "PA_HYBRID_INTAKE_005"),
    ],
)
def test_preflight_rejects_malformed_encrypted_and_over_page_pdf(
    tmp_path: Path,
    factory: object,
    limits: HybridIntakeLimits,
    code: str,
) -> None:
    path = tmp_path / "unsafe.pdf"
    if code == "PA_HYBRID_INTAKE_005":
        _write_pdf(path, (None, None))
    else:
        factory(path)  # type: ignore[operator]
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=limits)
    assert exc.value.code == code
    assert str(path) not in exc.value.message


def test_preflight_rejects_zero_page_and_over_byte_pdf(tmp_path: Path) -> None:
    pypdf, _ = _modules()
    zero_page = tmp_path / "zero.pdf"
    with zero_page.open("wb") as handle:
        pypdf.PdfWriter().write(handle)
    with pytest.raises(ProofAgentError, match="no pages"):
        preflight_hybrid_pdf(zero_page, limits=HybridIntakeLimits())

    ordinary = _write_pdf(tmp_path / "large.pdf")
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            ordinary,
            limits=HybridIntakeLimits(max_file_bytes=ordinary.stat().st_size - 1),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_002"


@pytest.mark.parametrize(
    ("embedded", "code"), [(False, "PA_HYBRID_INTAKE_007"), (True, "PA_HYBRID_INTAKE_008")]
)
def test_preflight_rejects_active_content_and_embedded_files(
    tmp_path: Path, embedded: bool, code: str
) -> None:
    path = _write_unsafe_pdf(tmp_path / "unsafe.pdf", embedded=embedded)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == code


def test_preflight_rejects_pdf_zip_polyglot_with_executable_payload(tmp_path: Path) -> None:
    path = _append_zip_payload(
        _write_pdf(tmp_path / "polyglot.pdf"),
        filename="payload.exe",
        content=b"MZ\x90\x00",
    )
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_009"


def test_preflight_rejects_non_archive_payload_after_pdf_eof(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "appended.pdf")
    with path.open("ab") as handle:
        handle.write(b"MZpayload-executable%%EOF")
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_009"


def test_preflight_rejects_payload_with_replayed_original_startxref(tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "replayed-xref.pdf")
    content = path.read_bytes()
    match = re.search(rb"startxref\s+(?P<offset>[0-9]+)\s+%%EOF\s*\Z", content)
    assert match is not None
    with path.open("ab") as handle:
        handle.write(b"MZpayload-executable\nstartxref\n" + match.group("offset") + b"\n%%EOF\n")

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_009"


def test_preflight_accepts_structurally_valid_incremental_revision(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_incremental_pdf(tmp_path / "incremental.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_ignores_revision_markers_inside_benign_content_stream(
    tmp_path: Path,
) -> None:
    result = preflight_hybrid_pdf(
        _write_pdf_with_revision_markers_in_content(tmp_path / "content-markers.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_bounds_revision_marker_candidates(tmp_path: Path) -> None:
    pypdf, generic = _modules()
    path = tmp_path / "many-markers.pdf"
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    content = generic.DecodedStreamObject()
    content.set_data((b"startxref\n0\n%%EOF\n" * 300))
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    with path.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_preflight_accepts_pdf_comments_at_incremental_object_boundaries(
    tmp_path: Path,
) -> None:
    result = preflight_hybrid_pdf(
        _write_commented_incremental_pdf(tmp_path / "commented-incremental.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_native_page_profile_stops_at_bounded_text_sample() -> None:
    _, generic = _modules()
    callback_returned = False
    content_stream = generic.DecodedStreamObject()
    content_stream.set_data(b"q")

    class LargeTextPage:
        mediabox = SimpleNamespace(width=612, height=792)

        def raw_get(self, _key: object) -> object:
            return content_stream

        def get_inherited(self, *, key: str, default: object) -> object:
            return default

        def extract_text(self, *, visitor_text: object) -> str:
            nonlocal callback_returned
            visitor_text("A" * 100_000, None, None, None, None)  # type: ignore[operator]
            callback_returned = True
            return "unbounded return should not be reached"

    profile = hybrid_intake_module._profile_page(LargeTextPage(), 1)

    assert callback_returned is False
    assert profile.native_extracted_character_count == 4096
    assert profile.requires_ocr is False


def test_preflight_accepts_ordinary_flate_compressed_page_content(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_compressed_content_pdf(
            tmp_path / "compressed.pdf",
            b"BT /F1 12 Tf 72 720 Td (Compressed policy text) Tj ET",
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_rejects_flate_bomb_before_real_pypdf_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    path = _write_compressed_content_pdf(
        tmp_path / "compressed-bomb.pdf",
        b"%" + b"A" * (2 * 1024 * 1024 + 1),
    )

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert extraction_called is False


def test_preflight_accepts_benign_nested_flate_form_xobjects(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_nested_form_pdf(
            tmp_path / "benign-forms.pdf",
            b"% bounded benign Form XObject content\n",
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_rejects_nested_form_bomb_before_real_pypdf_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    path = _write_nested_form_pdf(
        tmp_path / "form-bomb.pdf",
        b"%" + b"A" * (2 * 1024 * 1024 + 1),
    )

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert extraction_called is False


def test_preflight_rejects_non_image_non_form_xobject(tmp_path: Path) -> None:
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_unknown_xobject_pdf(tmp_path / "postscript-xobject.pdf"),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_preflight_accepts_bounded_compressed_tounicode_on_contentless_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    result = preflight_hybrid_pdf(
        _write_pdf_with_compressed_tounicode(
            tmp_path / "bounded-tounicode.pdf",
            b"/CIDInit /ProcSet findresource begin\nbegincmap\nendcmap\nend",
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1
    assert extraction_called is False


def test_preflight_rejects_tounicode_bomb_before_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    path = _write_pdf_with_compressed_tounicode(
        tmp_path / "tounicode-bomb.pdf",
        b"A" * (2 * 1024 * 1024 + 1),
    )

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert extraction_called is False


def test_preflight_rejects_excessive_repeated_form_do_work(tmp_path: Path) -> None:
    path = _write_nested_form_pdf(
        tmp_path / "repeated-escaped-form.pdf",
        b"% bounded form\n",
        page_do_count=300,
        escaped_page_form_name=True,
    )
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"


def test_preflight_accepts_bounded_compressed_type1_fontfile(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_pdf_with_compressed_type1_fontfile(
            tmp_path / "bounded-type1.pdf",
            b"%!PS\n/Encoding\ndup 65 /A put\neexec\n",
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_rejects_type1_fontfile_bomb_before_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    path = _write_pdf_with_compressed_type1_fontfile(
        tmp_path / "type1-fontfile-bomb.pdf",
        b"A" * (2 * 1024 * 1024 + 1),
    )

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert extraction_called is False


def test_preflight_rejects_content_token_flood_before_contentstream_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generic = import_module("pypdf.generic")
    original_init = generic.ContentStream.__init__
    materialization_entered = False

    def track_init(self: object, *args: object, **kwargs: object) -> None:
        nonlocal materialization_entered
        materialization_entered = True
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(generic.ContentStream, "__init__", track_init)
    path = _write_compressed_content_pdf(
        tmp_path / "token-flood.pdf",
        b"q\n" * 100_001,
    )

    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert materialization_entered is False


def test_preflight_rejects_excessive_descendant_font_entries(tmp_path: Path) -> None:
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_pdf_with_many_descendant_fonts(
                tmp_path / "many-descendant-fonts.pdf",
                count=300,
            ),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"


@pytest.mark.parametrize(
    "filters",
    [
        ("/ASCII85Decode",),
        ("/LZWDecode",),
        ("/RunLengthDecode",),
        ("/ASCII85Decode", "/FlateDecode"),
    ],
)
def test_preflight_accepts_common_standard_content_filters(
    tmp_path: Path,
    filters: tuple[str, ...],
) -> None:
    result = preflight_hybrid_pdf(
        _write_standard_filtered_content_pdf(tmp_path / "filtered.pdf", filters),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_accepts_chained_filters_with_null_decode_parms(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_standard_filtered_content_pdf(
            tmp_path / "null-decode-parms.pdf",
            ("/ASCII85Decode", "/FlateDecode"),
            null_decode_parms=True,
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_accepts_bounded_png_predictor_content(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_png_predictor_content_pdf(tmp_path / "predictor.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_rejects_runlength_output_over_limit_before_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_module = import_module("pypdf._page")
    original_extract_text = page_module.PageObject.extract_text
    extraction_called = False

    def track_extract_text(self: object, *args: object, **kwargs: object) -> str:
        nonlocal extraction_called
        extraction_called = True
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(page_module.PageObject, "extract_text", track_extract_text)
    path = _write_standard_filtered_content_pdf(
        tmp_path / "runlength-bomb.pdf",
        ("/RunLengthDecode",),
        b"A" * (2 * 1024 * 1024 + 1),
    )
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert extraction_called is False


def test_preflight_rejects_object_stream_bomb_before_pdfreader_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pypdf = import_module("pypdf")
    original_reader = pypdf.PdfReader
    reader_entered = False

    def track_reader(*args: object, **kwargs: object) -> object:
        nonlocal reader_entered
        reader_entered = True
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", track_reader)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_object_stream_pdf(
                tmp_path / "object-stream-bomb.pdf",
                padding_bytes=2 * 1024 * 1024 + 1,
            ),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert reader_entered is False


@pytest.mark.parametrize(
    "options",
    [
        {"nested_dictionary_before_type": True},
        {"indirect_filter_and_length": True},
        {"escaped_filter_name": True},
        {"escaped_filter_name": True, "indirect_filter_and_length": True},
        {"indirect_object_stream_type": True},
    ],
)
def test_preflight_accepts_bounded_structural_stream_dictionary_variants(
    tmp_path: Path,
    options: dict[str, bool | int],
) -> None:
    result = preflight_hybrid_pdf(
        _write_object_stream_pdf(
            tmp_path / "bounded-object-stream.pdf",
            padding_bytes=32,
            **options,
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_accepts_png_predicted_xref_stream(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_object_stream_pdf(
            tmp_path / "predicted-xref.pdf",
            padding_bytes=32,
            xref_predictor=True,
        ),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_structural_decode_parms_aligns_null_array_entries() -> None:
    tokens = [
        (b"<<", 0),
        (b"/DecodeParms", 1),
        (b"[", 1),
        (b"null", 1),
        (b"<<", 1),
        (b"/Predictor", 2),
        (b"12", 2),
        (b"/Columns", 2),
        (b"7", 2),
        (b">>", 1),
        (b"]", 1),
        (b">>", 0),
    ]

    values = hybrid_intake_module._structural_dictionary_decode_parms(tokens, 2)

    assert values == (None, {"/Predictor": 12, "/Columns": 7})


def test_structural_decode_parms_rejects_indirect_value() -> None:
    tokens = [
        (b"<<", 0),
        (b"/DecodeParms", 1),
        (b"7", 1),
        (b"0", 1),
        (b"R", 1),
        (b">>", 0),
    ]

    with pytest.raises(ProofAgentError) as exc:
        hybrid_intake_module._structural_dictionary_decode_parms(tokens, 1)

    assert exc.value.code == "PA_HYBRID_INTAKE_006"


@pytest.mark.parametrize(
    "options",
    [
        {"nested_dictionary_before_type": True},
        {"indirect_filter_and_length": True},
        {"escaped_object_stream_type": True},
        {"indirect_object_stream_type": True},
    ],
)
def test_preflight_rejects_structural_stream_variant_bombs_before_pdfreader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, bool | int],
) -> None:
    pypdf = import_module("pypdf")
    original_reader = pypdf.PdfReader
    reader_entered = False

    def track_reader(*args: object, **kwargs: object) -> object:
        nonlocal reader_entered
        reader_entered = True
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", track_reader)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_object_stream_pdf(
                tmp_path / "variant-object-stream-bomb.pdf",
                padding_bytes=2 * 1024 * 1024 + 1,
                **options,
            ),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert reader_entered is False


def test_preflight_rejects_escaped_xref_stream_bomb_before_pdfreader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pypdf = import_module("pypdf")
    original_reader = pypdf.PdfReader
    reader_entered = False

    def track_reader(*args: object, **kwargs: object) -> object:
        nonlocal reader_entered
        reader_entered = True
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", track_reader)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_object_stream_pdf(
                tmp_path / "escaped-xref-stream-bomb.pdf",
                padding_bytes=32,
                escaped_xref_type=True,
                xref_padding_bytes=2 * 1024 * 1024 + 1,
            ),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert reader_entered is False


def test_preflight_rejects_predicted_xref_stream_over_limit_before_pdfreader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pypdf = import_module("pypdf")
    original_reader = pypdf.PdfReader
    reader_entered = False

    def track_reader(*args: object, **kwargs: object) -> object:
        nonlocal reader_entered
        reader_entered = True
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", track_reader)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(
            _write_object_stream_pdf(
                tmp_path / "predicted-xref-bomb.pdf",
                padding_bytes=32,
                xref_padding_bytes=2 * 1024 * 1024 + 1,
                xref_predictor=True,
            ),
            limits=HybridIntakeLimits(),
        )
    assert exc.value.code == "PA_HYBRID_INTAKE_006"
    assert reader_entered is False


def test_preflight_ignores_structural_markers_inside_ordinary_stream_data(
    tmp_path: Path,
) -> None:
    pypdf, generic = _modules()
    path = tmp_path / "ordinary-marker-stream.pdf"
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    content = generic.DecodedStreamObject()
    content.set_data(b"% /Type /ObjStm /Type /XRef\n" * 300)
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject()
    with path.open("wb") as handle:
        writer.write(handle)

    result = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert result.page_count == 1


def test_preflight_rejects_unreferenced_embedded_stream_in_incremental_xref(
    tmp_path: Path,
) -> None:
    path = _write_incremental_pdf(
        tmp_path / "unreferenced-embedded.pdf",
        add_unreferenced_embedded_file=True,
    )
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_008"


def test_preflight_digest_and_profiles_use_same_immutable_opened_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_pdf(tmp_path / "source.pdf", ("Meaningful native policy text",))
    original_bytes = path.read_bytes()
    replacement = _write_pdf(tmp_path / "replacement.pdf")
    original_is_zipfile = hybrid_intake_module.zipfile.is_zipfile

    def replace_path_after_snapshot(source: object) -> bool:
        os.replace(replacement, path)
        return original_is_zipfile(source)

    monkeypatch.setattr(hybrid_intake_module.zipfile, "is_zipfile", replace_path_after_snapshot)

    result = preflight_hybrid_pdf(path, limits=HybridIntakeLimits())

    assert result.source_sha256 == hashlib.sha256(original_bytes).hexdigest()
    assert result.source_size_bytes == len(original_bytes)
    assert result.page_profiles[0].requires_ocr is False
    assert path.read_bytes() != original_bytes


@pytest.mark.parametrize(
    "action_type",
    ["/URI", "/SubmitForm", "/GoToR", "/FutureAction"],
)
def test_preflight_rejects_pdf_action_dictionaries(
    tmp_path: Path,
    action_type: str,
) -> None:
    path = _write_action_pdf(tmp_path / "action.pdf", action_type)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_007"


def test_preflight_preserves_benign_non_action_s_dictionary(tmp_path: Path) -> None:
    result = preflight_hybrid_pdf(
        _write_benign_transparency_pdf(tmp_path / "transparency.pdf"),
        limits=HybridIntakeLimits(),
    )
    assert result.page_count == 1


def test_preflight_requires_regular_non_symlink_pdf(tmp_path: Path) -> None:
    target = _write_pdf(tmp_path / "target.pdf")
    symlink = tmp_path / "link.pdf"
    symlink.symlink_to(target)
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(symlink, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_001"


@pytest.mark.parametrize("value", [0, -1, True, "5"])
def test_hybrid_limits_are_strict_positive_integers(value: object) -> None:
    with pytest.raises(ValidationError):
        HybridIntakeLimits(max_batch_files=value)  # type: ignore[arg-type]


def test_hybrid_limits_forbid_unknown_configuration() -> None:
    with pytest.raises(ValidationError):
        HybridIntakeLimits.model_validate({"endpoint": "https://example.invalid"})
