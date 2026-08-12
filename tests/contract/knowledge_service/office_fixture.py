from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def docx_with_paragraphs(*paragraphs: str) -> bytes:
    document_body = "".join(
        (
            "<w:p><w:r><w:t>"
            f"{_xml_text(paragraph)}"
            "</w:t></w:r></w:p>"
        )
        for paragraph in paragraphs
    )
    return _docx_package(document_body)


def docx_with_table(rows: tuple[tuple[str, ...], ...]) -> bytes:
    table_rows = "".join(
        "<w:tr>"
        + "".join(
            "<w:tc><w:p><w:r><w:t>"
            f"{_xml_text(value)}"
            "</w:t></w:r></w:p></w:tc>"
            for value in row
        )
        + "</w:tr>"
        for row in rows
    )
    return _docx_package(f"<w:tbl>{table_rows}</w:tbl>")


def pptx_with_slide_shapes(*slides: tuple[tuple[int, str], ...]) -> bytes:
    slide_ids = "".join(
        f'<p:sldId id="{255 + slide_number}" r:id="rId{slide_number}"/>'
        for slide_number in range(1, len(slides) + 1)
    )
    relationships = "".join(
        (
            f'<Relationship Id="rId{slide_number}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/slide" '
            f'Target="slides/slide{slide_number}.xml"/>'
        )
        for slide_number in range(1, len(slides) + 1)
    )
    overrides = "".join(
        (
            f'<Override PartName="/ppt/slides/slide{slide_number}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'presentationml.slide+xml"/>'
        )
        for slide_number in range(1, len(slides) + 1)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            f"{overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:presentation '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
            "</p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>"
        ),
    }
    for slide_number, shapes in enumerate(slides, start=1):
        shape_xml = "".join(
            (
                "<p:sp><p:nvSpPr>"
                f'<p:cNvPr id="{shape_id}" name="Shape {shape_id}"/>'
                "<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/>"
                "<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>"
                f"{_xml_text(text)}"
                "</a:t></a:r></a:p></p:txBody></p:sp>"
            )
            for shape_id, text in shapes
        )
        files[f"ppt/slides/slide{slide_number}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>"
            f"{shape_xml}</p:spTree></p:cSld></p:sld>"
        )
    return _zip_package(files)


def _docx_package(document_body: str) -> bytes:
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{document_body}<w:sectPr/></w:body>"
            "</w:document>"
        ),
    }
    return _zip_package(files)


def _zip_package(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return output.getvalue()


def _xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
