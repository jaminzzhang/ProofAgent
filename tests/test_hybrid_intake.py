from __future__ import annotations

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
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _write_nested_form_pdf(path: Path, form_content: bytes) -> Path:
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
    page_content.set_data(b"/Outer Do")
    page[generic.NameObject("/Contents")] = writer._add_object(page_content)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {
            generic.NameObject("/XObject"): generic.DictionaryObject(
                {generic.NameObject("/Outer"): outer_ref}
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
    callback_returned = False

    class LargeTextPage:
        mediabox = SimpleNamespace(width=612, height=792)

        def raw_get(self, _key: object) -> object:
            raise KeyError

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
