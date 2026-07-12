from __future__ import annotations

import hashlib
from importlib import import_module
from importlib.util import find_spec
import math
from io import BytesIO
from pathlib import Path
from types import ModuleType
import zipfile

import pytest
from pydantic import ValidationError

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
        handle.write(b"MZ\x90\x00executable")
    with pytest.raises(ProofAgentError) as exc:
        preflight_hybrid_pdf(path, limits=HybridIntakeLimits())
    assert exc.value.code == "PA_HYBRID_INTAKE_009"


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
