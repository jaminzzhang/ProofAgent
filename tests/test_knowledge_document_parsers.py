from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType

import pytest

from proof_agent.capabilities.knowledge.ingestion import parse_quarantined_upload
from proof_agent.errors import ProofAgentError

requires_pypdf = pytest.mark.skipif(find_spec("pypdf") is None, reason="pypdf is not installed")


def _pypdf_modules() -> tuple[ModuleType, ModuleType]:
    return import_module("pypdf"), import_module("pypdf.generic")


def _write_pdf(
    path: Path,
    *,
    text_operand: bytes | None = None,
    encoding: str | None = None,
    to_unicode: bytes | None = None,
    page_count: int = 1,
) -> None:
    pypdf, pypdf_generic = _pypdf_modules()
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)

    if text_operand is not None:
        page = writer.pages[0]
        font = pypdf_generic.DictionaryObject(
            {
                pypdf_generic.NameObject("/Type"): pypdf_generic.NameObject("/Font"),
                pypdf_generic.NameObject("/Subtype"): pypdf_generic.NameObject("/Type1"),
                pypdf_generic.NameObject("/BaseFont"): pypdf_generic.NameObject("/Helvetica"),
            }
        )
        if encoding is not None:
            font[pypdf_generic.NameObject("/Encoding")] = pypdf_generic.NameObject(encoding)
        if to_unicode is not None:
            unicode_stream = pypdf_generic.DecodedStreamObject()
            unicode_stream.set_data(to_unicode)
            font[pypdf_generic.NameObject("/ToUnicode")] = writer._add_object(unicode_stream)

        content_stream = pypdf_generic.DecodedStreamObject()
        content_stream.set_data(b"BT /F1 12 Tf 72 720 Td " + text_operand + b" Tj ET")
        page[pypdf_generic.NameObject("/Resources")] = pypdf_generic.DictionaryObject(
            {
                pypdf_generic.NameObject("/Font"): pypdf_generic.DictionaryObject(
                    {pypdf_generic.NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        page[pypdf_generic.NameObject("/Contents")] = writer._add_object(content_stream)

    with path.open("wb") as handle:
        writer.write(handle)


def _write_encrypted_pdf(path: Path) -> None:
    pypdf, _ = _pypdf_modules()
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("password")
    with path.open("wb") as handle:
        writer.write(handle)


def _simple_to_unicode_cmap() -> bytes:
    return b"""
/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
1 beginbfchar
<01> <4E2D>
endbfchar
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


def test_parse_markdown_normalizes_utf8_line_endings_and_unicode(tmp_path: Path) -> None:
    path = tmp_path / "policy.md"
    path.write_bytes("Cafe\u0301\r\n\rPolicy\r".encode())

    parsed = parse_quarantined_upload(
        path,
        filename="policy.md",
        content_type="text/markdown",
    )

    assert parsed.text == "Caf\u00e9\n\nPolicy\n"
    assert parsed.page_count is None
    assert parsed.parser_metadata.adapter == "markdown"
    assert parsed.parser_metadata.fingerprint_identity == "markdown:utf-8:v1"
    assert parsed.parser_metadata.parsed_text_sha256 is not None


@pytest.mark.parametrize(
    ("text_operand", "encoding", "to_unicode", "expected_text"),
    [
        (b"(Policy text)", None, None, "Policy text"),
        (b"(caf\\351)", "/WinAnsiEncoding", None, "caf\u00e9"),
        (b"<01>", None, _simple_to_unicode_cmap(), "\u4e2d"),
    ],
)
@requires_pypdf
def test_parse_pdf_extracts_supported_text_encodings(
    tmp_path: Path,
    text_operand: bytes,
    encoding: str | None,
    to_unicode: bytes | None,
    expected_text: str,
) -> None:
    pypdf, _ = _pypdf_modules()
    path = tmp_path / "policy.pdf"
    _write_pdf(path, text_operand=text_operand, encoding=encoding, to_unicode=to_unicode)

    parsed = parse_quarantined_upload(
        path,
        filename="policy.pdf",
        content_type="application/pdf",
    )

    assert expected_text in parsed.text
    assert parsed.page_count == 1
    assert parsed.parser_metadata.adapter == "pypdf"
    assert parsed.parser_metadata.library_version == pypdf.__version__
    assert parsed.parser_metadata.fingerprint_identity == f"pypdf:v1@{pypdf.__version__}"


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("policy.pdf", "text/markdown", b"%PDF-1.7\n"),
        ("policy.md", "application/pdf", b"# Policy\n"),
        ("policy.pdf", "application/pdf", b"# Policy\n"),
        ("policy.md", "text/markdown", b"%PDF-1.7\n"),
        ("policy.exe", "application/octet-stream", b"MZ"),
        ("policy.md", "text/markdown", b"PK\x03\x04"),
    ],
)
def test_parse_quarantined_upload_rejects_mismatches_and_unsupported_content(
    tmp_path: Path,
    filename: str,
    content_type: str,
    content: bytes,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename=filename, content_type=content_type)

    assert exc.value.code == "PA_INGESTION_002"


def test_parse_markdown_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "policy.md"
    path.write_bytes(b"\xff")

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename="policy.md", content_type="text/markdown")

    assert exc.value.code == "PA_INGESTION_002"


@requires_pypdf
def test_parse_pdf_rejects_malformed_pdf(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"%PDF-1.7\nnot-a-pdf")

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename="policy.pdf", content_type="application/pdf")

    assert exc.value.code == "PA_INGESTION_002"


@requires_pypdf
def test_parse_pdf_rejects_encrypted_pdf(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    _write_encrypted_pdf(path)

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename="policy.pdf", content_type="application/pdf")

    assert exc.value.code == "PA_INGESTION_002"


@requires_pypdf
def test_parse_pdf_rejects_blank_pdf(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    _write_pdf(path)

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename="policy.pdf", content_type="application/pdf")

    assert exc.value.code == "PA_INGESTION_002"


@requires_pypdf
def test_parse_pdf_rejects_more_than_500_pages(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    _write_pdf(path, page_count=501)

    with pytest.raises(ProofAgentError) as exc:
        parse_quarantined_upload(path, filename="policy.pdf", content_type="application/pdf")

    assert exc.value.code == "PA_INGESTION_002"
