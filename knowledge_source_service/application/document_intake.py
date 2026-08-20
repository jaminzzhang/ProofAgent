"""S3-first deterministic intake for Markdown and plain-text Source Versions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
import re
from typing import Literal
import warnings
from xml.etree.ElementTree import Element, ParseError, fromstring
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from PIL import Image, UnidentifiedImageError

from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.identities import content_identifier, sha256_json, sha256_text
from knowledge_source_service.domain.knowledge_catalog import (
    DocxParagraphDocumentCitation,
    DocxTableCellDocumentCitation,
    DocumentEvidenceUnit,
    DocumentSourceVersion,
    HtmlDomDocumentCitation,
    OcrRegionDocumentCitation,
    PdfPageDocumentCitation,
    PptxShapeDocumentCitation,
    TextLinesDocumentCitation,
)
from knowledge_source_service.domain.publications import PublishedDocumentSourceVersion
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogWriter
from knowledge_source_service.ports.ocr import DocumentOcrExtractor, OcrDocument


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_PRESENTATION_NAMESPACE = (
    "http://schemas.openxmlformats.org/presentationml/2006/main"
)
_DRAWING_NAMESPACE = "http://schemas.openxmlformats.org/drawingml/2006/main"
_OFFICE_RELATIONSHIP_NAMESPACE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_RELATIONSHIP_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_MAX_OOXML_PARTS = 2_000
_MAX_OOXML_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_DOCUMENT_STRUCTURE_SCHEMA = "document-structure-graph.v2"
_EVIDENCE_MANIFEST_SCHEMA = "evidence-unit-manifest.v1"
_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/tiff"}

_SUPPORTED_MEDIA_TYPES = {
    "application/pdf",
    _DOCX_MEDIA_TYPE,
    _PPTX_MEDIA_TYPE,
    *_IMAGE_MEDIA_TYPES,
    "text/html",
    "text/markdown",
    "text/plain",
}
_HTML_BLOCK_TAGS = {
    "blockquote",
    "dd",
    "dt",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "pre",
    "td",
    "th",
}
_HTML_SUPPRESSED_TAGS = {"script", "style", "template", "noscript"}
_HTML_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True)
class DocumentIntakeCommand:
    knowledge_space_id: str
    knowledge_source_id: str
    display_filename: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class _ParsedDocumentNode:
    kind: Literal["heading", "paragraph"]
    text: str
    start_line: int
    end_line: int
    page_number: int | None = None
    docx_paragraph_number: int | None = None
    docx_table_cell: tuple[int, int, int] | None = None
    pptx_shape: tuple[int, int] | None = None
    html_dom_path: str | None = None
    ocr_region: tuple[int, int, int, int, int] | None = None


@dataclass
class _OpenHtmlBlock:
    tag: str
    kind: Literal["heading", "paragraph"]
    start_line: int
    fragments: list[str]
    dom_path: str


@dataclass
class _OpenHtmlElement:
    tag: str
    dom_path: str
    child_counts: dict[str, int]


class DocumentIntakeApplication:
    """Finalize immutable artifacts before exposing one Source Version in the catalog."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        pipeline_revision: str,
        max_content_bytes: int,
        ocr_extractor: DocumentOcrExtractor | None = None,
        max_image_pixels: int = 40_000_000,
        max_image_frames: int = 500,
    ) -> None:
        if not pipeline_revision.strip():
            raise ValueError("pipeline_revision must not be blank")
        if max_content_bytes < 1:
            raise ValueError("max_content_bytes must be positive")
        if max_image_pixels < 1 or max_image_frames < 1:
            raise ValueError("image intake bounds must be positive")
        self._artifacts = artifacts
        self._catalog = catalog
        self._pipeline_revision = pipeline_revision
        self._max_content_bytes = max_content_bytes
        self._ocr_extractor = ocr_extractor
        self._max_image_pixels = max_image_pixels
        self._max_image_frames = max_image_frames

    def create_source_version(
        self,
        command: DocumentIntakeCommand,
    ) -> PublishedDocumentSourceVersion:
        _validate_authority_id(command.knowledge_space_id, "knowledge_space_id")
        _validate_authority_id(command.knowledge_source_id, "knowledge_source_id")
        if command.media_type not in _SUPPORTED_MEDIA_TYPES:
            raise ValueError("unsupported document media type")
        if type(command.content) is not bytes or not command.content:
            raise ValueError("document content must be nonempty exact bytes")
        if len(command.content) > self._max_content_bytes:
            raise ValueError("document content exceeds the admitted size limit")
        text: str | None = None
        ocr_document: OcrDocument | None = None
        image_sizes: tuple[tuple[int, int], ...] = ()
        pdf_nodes: list[_ParsedDocumentNode] | None = None
        pdf_ocr_pages: frozenset[int] = frozenset()
        if command.media_type == "application/pdf":
            if not command.content.startswith(b"%PDF-"):
                raise ValueError("PDF content signature is invalid")
            pdf_nodes, pdf_page_count = _parse_pdf_nodes(command.content)
            native_pages = frozenset(
                node.page_number for node in pdf_nodes if node.page_number is not None
            )
            pdf_ocr_pages = frozenset(range(1, pdf_page_count + 1)) - native_pages
            if pdf_ocr_pages:
                if self._ocr_extractor is None:
                    raise ValueError("PDF page has no native text; OCR processing is required")
                ocr_document = self._ocr_extractor.extract(
                    media_type=command.media_type,
                    content=command.content,
                )
                if not isinstance(ocr_document, OcrDocument):
                    raise ValueError("OCR extractor returned an invalid result")
                image_sizes = _ocr_document_page_sizes(
                    ocr_document,
                    expected_page_count=pdf_page_count,
                )
        elif command.media_type == _DOCX_MEDIA_TYPE:
            if not command.content.startswith(b"PK\x03\x04"):
                raise ValueError("DOCX content signature is invalid")
        elif command.media_type == _PPTX_MEDIA_TYPE:
            if not command.content.startswith(b"PK\x03\x04"):
                raise ValueError("PPTX content signature is invalid")
        elif command.media_type in _IMAGE_MEDIA_TYPES:
            image_sizes = _validate_image_document(
                media_type=command.media_type,
                content=command.content,
                max_pixels=self._max_image_pixels,
                max_frames=self._max_image_frames,
            )
            if self._ocr_extractor is None:
                raise ValueError("OCR extractor is not configured")
            ocr_document = self._ocr_extractor.extract(
                media_type=command.media_type,
                content=command.content,
            )
            if not isinstance(ocr_document, OcrDocument):
                raise ValueError("OCR extractor returned an invalid result")
            if ocr_document.pages and (
                _ocr_document_page_sizes(
                    ocr_document,
                    expected_page_count=len(image_sizes),
                )
                != image_sizes
            ):
                raise ValueError("OCR image dimensions do not match the admitted original")
        else:
            if b"\x00" in command.content:
                raise ValueError("document content contains a forbidden NUL byte")
            try:
                text = command.content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("document content must be valid UTF-8") from error
            if not text.strip():
                raise ValueError("document content must contain visible text")

        content_digest = f"sha256:{sha256(command.content).hexdigest()}"
        lineage_payload: dict[str, object] = {
            "schema": "document-processing-lineage.v1",
            "pipeline_revision": self._pipeline_revision,
            "media_type": command.media_type,
            "document_structure_schema": _DOCUMENT_STRUCTURE_SCHEMA,
            "evidence_manifest_schema": _EVIDENCE_MANIFEST_SCHEMA,
        }
        if ocr_document is not None:
            lineage_payload["ocr_model_revision"] = ocr_document.model_revision
        processing_lineage_digest = sha256_json(lineage_payload)
        version_digest = sha256_json(
            {
                "knowledge_space_id": command.knowledge_space_id,
                "knowledge_source_id": command.knowledge_source_id,
                "original_digest": content_digest,
                "processing_lineage_digest": processing_lineage_digest,
            }
        )
        source_version_id = content_identifier("source-version", version_digest)
        if command.media_type == "application/pdf":
            if pdf_nodes is None:
                raise ValueError("PDF preflight result is missing")
            parsed_pdf_nodes = list(pdf_nodes)
            if ocr_document is not None:
                ocr_nodes = _ocr_nodes(
                    document=ocr_document,
                    image_sizes=image_sizes,
                    included_pages=pdf_ocr_pages,
                )
                if not pdf_ocr_pages <= {
                    node.ocr_region[0]
                    for node in ocr_nodes
                    if node.ocr_region is not None
                }:
                    raise ValueError("OCR did not produce text for every required PDF page")
                parsed_pdf_nodes.extend(ocr_nodes)
            parsed_pdf_nodes.sort(
                key=lambda node: (
                    node.start_line,
                    node.ocr_region or (node.start_line, 0, 0, 0, 0),
                    node.text,
                )
            )
            evidence_units, structure_nodes = _build_document_units(
                source_version_id,
                parsed_pdf_nodes,
            )
        elif command.media_type == _DOCX_MEDIA_TYPE:
            evidence_units, structure_nodes = _parse_docx_document(
                source_version_id=source_version_id,
                content=command.content,
            )
        elif command.media_type == _PPTX_MEDIA_TYPE:
            evidence_units, structure_nodes = _parse_pptx_document(
                source_version_id=source_version_id,
                content=command.content,
            )
        elif command.media_type in _IMAGE_MEDIA_TYPES:
            if ocr_document is None:
                raise ValueError("OCR result is missing")
            evidence_units, structure_nodes = _parse_ocr_document(
                source_version_id=source_version_id,
                document=ocr_document,
                image_sizes=image_sizes,
            )
        else:
            evidence_units, structure_nodes = _parse_document(
                source_version_id=source_version_id,
                media_type=command.media_type,
                text=text or "",
            )
        if not evidence_units:
            raise ValueError("document produced no independently citable Evidence Unit")
        version = DocumentSourceVersion(
            knowledge_space_id=command.knowledge_space_id,
            knowledge_source_id=command.knowledge_source_id,
            knowledge_source_version_id=source_version_id,
            media_type=command.media_type,
            evidence_units=evidence_units,
        )
        key_root = (
            f"spaces/{command.knowledge_space_id}/sources/{command.knowledge_source_id}/"
            f"versions/{source_version_id}"
        )
        original = self._put_and_verify(
            object_key=f"{key_root}/originals/{content_digest.removeprefix('sha256:')}.bin",
            content=command.content,
            media_type=command.media_type,
        )
        canonical_content = _canonical_json_bytes(
            {
                "schema_version": _DOCUMENT_STRUCTURE_SCHEMA,
                "knowledge_source_version_id": source_version_id,
                "media_type": command.media_type,
                "processing_lineage_digest": processing_lineage_digest,
                "nodes": structure_nodes,
            }
        )
        canonical_digest = f"sha256:{sha256(canonical_content).hexdigest()}"
        canonical = self._put_and_verify(
            object_key=(
                f"{key_root}/canonical/{canonical_digest.removeprefix('sha256:')}.json"
            ),
            content=canonical_content,
            media_type="application/vnd.knowledge.document-structure+json",
        )
        manifest_content = _canonical_json_bytes(
            {
                "schema_version": _EVIDENCE_MANIFEST_SCHEMA,
                "knowledge_source_version_id": source_version_id,
                "processing_lineage_digest": processing_lineage_digest,
                "canonical_artifact_sha256": canonical.sha256,
                "evidence_units": [
                    {
                        "evidence_unit_id": unit.evidence_unit_id,
                        "text": unit.text,
                        "content_hash": unit.content_hash,
                        "citation_locator": _citation_payload(unit),
                    }
                    for unit in evidence_units
                ],
            }
        )
        evidence_manifest = self._put_and_verify(
            object_key=f"{key_root}/evidence-unit-manifest.json",
            content=manifest_content,
            media_type="application/vnd.knowledge.evidence-unit-manifest+json",
        )
        publication = PublishedDocumentSourceVersion(
            version=version,
            original_artifact=original,
            canonical_artifact=canonical,
            evidence_manifest_artifact=evidence_manifest,
            processing_lineage_digest=processing_lineage_digest,
        )
        self._catalog.put_document_source_version(publication)
        return publication

    def _put_and_verify(
        self,
        *,
        object_key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactReference:
        reference = self._artifacts.put_immutable(
            object_key=object_key,
            content=content,
            media_type=media_type,
        )
        if self._artifacts.get_exact(reference) != content:
            raise ValueError("finalized immutable artifact failed exact verification")
        return reference


def _parse_document(
    *,
    source_version_id: str,
    media_type: str,
    text: str,
) -> tuple[tuple[DocumentEvidenceUnit, ...], list[dict[str, object]]]:
    parsed_nodes = (
        _parse_html(text)
        if media_type == "text/html"
        else _parse_text_lines(text, markdown=media_type == "text/markdown")
    )
    return _build_document_units(source_version_id, parsed_nodes)


def _build_document_units(
    source_version_id: str,
    parsed_nodes: list[_ParsedDocumentNode],
) -> tuple[tuple[DocumentEvidenceUnit, ...], list[dict[str, object]]]:
    units: list[DocumentEvidenceUnit] = []
    nodes: list[dict[str, object]] = [
        {
            "kind": node.kind,
            "text": node.text,
            "citation_locator": _node_citation_payload(node),
        }
        for node in parsed_nodes
    ]
    for node in parsed_nodes:
        if node.kind == "heading":
            continue
        content_hash = sha256_text(node.text)
        evidence_unit_id = content_identifier(
            "evidence-unit",
            sha256_json(
                {
                    "knowledge_source_version_id": source_version_id,
                    "citation_locator": _node_citation_payload(node),
                    "content_hash": content_hash,
                }
            ),
        )
        units.append(
            DocumentEvidenceUnit(
                evidence_unit_id=evidence_unit_id,
                text=node.text,
                content_hash=content_hash,
                citation_locator=(
                    PdfPageDocumentCitation(page_number=node.page_number)
                    if node.page_number is not None
                    else DocxParagraphDocumentCitation(
                        paragraph_number=node.docx_paragraph_number
                    )
                    if node.docx_paragraph_number is not None
                    else DocxTableCellDocumentCitation(
                        table_number=node.docx_table_cell[0],
                        row_number=node.docx_table_cell[1],
                        column_number=node.docx_table_cell[2],
                    )
                    if node.docx_table_cell is not None
                    else PptxShapeDocumentCitation(
                        slide_number=node.pptx_shape[0],
                        shape_id=node.pptx_shape[1],
                    )
                    if node.pptx_shape is not None
                    else HtmlDomDocumentCitation(dom_path=node.html_dom_path)
                    if node.html_dom_path is not None
                    else OcrRegionDocumentCitation(
                        page_number=node.ocr_region[0],
                        x_min=node.ocr_region[1],
                        y_min=node.ocr_region[2],
                        x_max=node.ocr_region[3],
                        y_max=node.ocr_region[4],
                    )
                    if node.ocr_region is not None
                    else TextLinesDocumentCitation(
                        start_line=node.start_line,
                        end_line=node.end_line,
                    )
                ),
            )
        )
    return tuple(units), nodes


def _parse_pdf_nodes(content: bytes) -> tuple[list[_ParsedDocumentNode], int]:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted PDF content is not admitted")
        if not reader.pages or len(reader.pages) > 10_000:
            raise ValueError("PDF page count is outside the admitted bound")
        nodes = [
            _ParsedDocumentNode(
                kind="paragraph",
                text=normalized,
                start_line=page_number,
                end_line=page_number,
                page_number=page_number,
            )
            for page_number, page in enumerate(reader.pages, start=1)
            for raw_text in (page.extract_text(extraction_mode="plain") or "",)
            for line in raw_text.splitlines()
            if (normalized := " ".join(line.split()))
        ]
    except PdfReadError as error:
        raise ValueError("PDF structure is invalid") from error
    return nodes, len(reader.pages)


def _validate_image_document(
    *,
    media_type: str,
    content: bytes,
    max_pixels: int,
    max_frames: int,
) -> tuple[tuple[int, int], ...]:
    valid_signature = (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        if media_type == "image/png"
        else content.startswith(b"\xff\xd8\xff")
        if media_type == "image/jpeg"
        else content.startswith((b"II*\x00", b"MM\x00*"))
    )
    if not valid_signature:
        raise ValueError("image content signature does not match its media type")
    expected_format = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/tiff": "TIFF",
    }[media_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format:
                    raise ValueError(
                        "image decoder format does not match its media type"
                    )
                frame_count = int(getattr(image, "n_frames", 1))
                if not 1 <= frame_count <= max_frames:
                    raise ValueError("image frame count is outside the admitted bound")
                sizes: list[tuple[int, int]] = []
                total_pixels = 0
                for frame_number in range(frame_count):
                    image.seek(frame_number)
                    width, height = image.size
                    if width < 1 or height < 1:
                        raise ValueError("image dimensions are invalid")
                    total_pixels += width * height
                    if total_pixels > max_pixels:
                        raise ValueError("image pixels exceed the admitted bound")
                    image.load()
                    sizes.append((width, height))
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as error:
        raise ValueError("image structure is invalid") from error
    return tuple(sizes)


def _parse_ocr_document(
    *,
    source_version_id: str,
    document: OcrDocument,
    image_sizes: tuple[tuple[int, int], ...],
) -> tuple[tuple[DocumentEvidenceUnit, ...], list[dict[str, object]]]:
    return _build_document_units(
        source_version_id,
        _ocr_nodes(document=document, image_sizes=image_sizes),
    )


def _ocr_document_page_sizes(
    document: OcrDocument,
    *,
    expected_page_count: int,
) -> tuple[tuple[int, int], ...]:
    if len(document.pages) != expected_page_count:
        raise ValueError("OCR page metadata does not match the admitted document")
    return tuple((page.width, page.height) for page in document.pages)


def _ocr_nodes(
    *,
    document: OcrDocument,
    image_sizes: tuple[tuple[int, int], ...],
    included_pages: frozenset[int] | None = None,
) -> list[_ParsedDocumentNode]:
    nodes: list[_ParsedDocumentNode] = []
    for region in sorted(
        document.regions,
        key=lambda item: (
            item.page_number,
            item.y_min,
            item.x_min,
            item.y_max,
            item.x_max,
            item.text,
        ),
    ):
        if included_pages is not None and region.page_number not in included_pages:
            continue
        if region.page_number > len(image_sizes):
            raise ValueError("OCR region references an unknown image page")
        width, height = image_sizes[region.page_number - 1]
        if region.x_max > width or region.y_max > height:
            raise ValueError("OCR region exceeds its image page bounds")
        normalized = " ".join(region.text.split())
        nodes.append(
            _ParsedDocumentNode(
                kind="paragraph",
                text=normalized,
                start_line=region.page_number,
                end_line=region.page_number,
                ocr_region=(
                    region.page_number,
                    region.x_min,
                    region.y_min,
                    region.x_max,
                    region.y_max,
                ),
            )
        )
    return nodes


def _parse_docx_document(
    *,
    source_version_id: str,
    content: bytes,
) -> tuple[tuple[DocumentEvidenceUnit, ...], list[dict[str, object]]]:
    parts = _safe_ooxml_parts(content, required={"word/document.xml"})
    document = _xml_root(parts["word/document.xml"], "DOCX document")
    body = document.find(f"./{{{_WORD_NAMESPACE}}}body")
    if body is None:
        raise ValueError("DOCX document body is missing")
    nodes: list[_ParsedDocumentNode] = []
    paragraph_number = 0
    table_number = 0
    for child in body:
        if child.tag == f"{{{_WORD_NAMESPACE}}}p":
            paragraph_number += 1
            text = _word_paragraph_text(child)
            if text:
                nodes.append(
                    _docx_paragraph_node(
                        paragraph=child,
                        paragraph_number=paragraph_number,
                        text=text,
                    )
                )
        elif child.tag == f"{{{_WORD_NAMESPACE}}}tbl":
            table_number += 1
            nodes.extend(_docx_table_nodes(child, table_number=table_number))
    if not nodes:
        raise ValueError("DOCX has no supported visible text")
    return _build_document_units(source_version_id, nodes)


def _docx_paragraph_node(
    *,
    paragraph: Element,
    paragraph_number: int,
    text: str,
) -> _ParsedDocumentNode:
    style = paragraph.find(
        f"./{{{_WORD_NAMESPACE}}}pPr/{{{_WORD_NAMESPACE}}}pStyle"
    )
    style_value = (
        style.attrib.get(f"{{{_WORD_NAMESPACE}}}val", "")
        if style is not None
        else ""
    )
    return _ParsedDocumentNode(
        kind=(
            "heading" if style_value.casefold().startswith("heading") else "paragraph"
        ),
        text=text,
        start_line=paragraph_number,
        end_line=paragraph_number,
        docx_paragraph_number=paragraph_number,
    )


def _docx_table_nodes(table: Element, *, table_number: int) -> list[_ParsedDocumentNode]:
    rows = table.findall(f"./{{{_WORD_NAMESPACE}}}tr")
    if len(rows) > 999:
        raise ValueError("DOCX table exceeds the admitted row bound")
    nodes: list[_ParsedDocumentNode] = []
    for row_number, row in enumerate(rows, start=1):
        cells = row.findall(f"./{{{_WORD_NAMESPACE}}}tc")
        if len(cells) > 999:
            raise ValueError("DOCX table exceeds the admitted column bound")
        for column_number, cell in enumerate(cells, start=1):
            text = "\n".join(
                paragraph_text
                for paragraph in cell.findall(f".//{{{_WORD_NAMESPACE}}}p")
                if (paragraph_text := _word_paragraph_text(paragraph))
            )
            if not text:
                continue
            coordinate = (
                table_number * 1_000_000 + row_number * 1_000 + column_number
            )
            nodes.append(
                _ParsedDocumentNode(
                    kind="paragraph",
                    text=text,
                    start_line=coordinate,
                    end_line=coordinate,
                    docx_table_cell=(table_number, row_number, column_number),
                )
            )
    return nodes


def _parse_pptx_document(
    *,
    source_version_id: str,
    content: bytes,
) -> tuple[tuple[DocumentEvidenceUnit, ...], list[dict[str, object]]]:
    required = {
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }
    parts = _safe_ooxml_parts(content, required=required)
    presentation = _xml_root(parts["ppt/presentation.xml"], "PPTX presentation")
    relationships = _xml_root(
        parts["ppt/_rels/presentation.xml.rels"],
        "PPTX presentation relationships",
    )
    relationship_targets = {
        relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
        for relation in relationships.findall(
            f".//{{{_RELATIONSHIP_NAMESPACE}}}Relationship"
        )
        if relation.attrib.get("Type", "").endswith("/slide")
    }
    slide_ids = presentation.findall(
        f"./{{{_PRESENTATION_NAMESPACE}}}sldIdLst/"
        f"{{{_PRESENTATION_NAMESPACE}}}sldId"
    )
    if not slide_ids or len(slide_ids) > 1_000:
        raise ValueError("PPTX slide count is outside the admitted bound")
    nodes: list[_ParsedDocumentNode] = []
    for slide_number, slide_id in enumerate(slide_ids, start=1):
        relationship_id = slide_id.attrib.get(
            f"{{{_OFFICE_RELATIONSHIP_NAMESPACE}}}id", ""
        )
        target = relationship_targets.get(relationship_id, "")
        if not target.startswith("slides/") or ".." in target.split("/"):
            raise ValueError("PPTX slide relationship is invalid")
        part_name = f"ppt/{target}"
        if part_name not in parts:
            raise ValueError("PPTX slide part is missing")
        slide = _xml_root(parts[part_name], "PPTX slide")
        seen_shape_ids: set[int] = set()
        for shape in slide.findall(f".//{{{_PRESENTATION_NAMESPACE}}}sp"):
            identity = shape.find(
                f"./{{{_PRESENTATION_NAMESPACE}}}nvSpPr/"
                f"{{{_PRESENTATION_NAMESPACE}}}cNvPr"
            )
            raw_shape_id = identity.attrib.get("id", "") if identity is not None else ""
            try:
                shape_id = int(raw_shape_id)
            except ValueError as error:
                raise ValueError("PPTX shape identity is invalid") from error
            if not 1 <= shape_id <= 999_999 or shape_id in seen_shape_ids:
                raise ValueError("PPTX shape identity is invalid")
            seen_shape_ids.add(shape_id)
            text = " ".join(
                " ".join((item.text or "").split())
                for item in shape.iter(f"{{{_DRAWING_NAMESPACE}}}t")
                if (item.text or "").strip()
            ).strip()
            if not text:
                continue
            coordinate = slide_number * 1_000_000 + shape_id
            nodes.append(
                _ParsedDocumentNode(
                    kind="paragraph",
                    text=text,
                    start_line=coordinate,
                    end_line=coordinate,
                    pptx_shape=(slide_number, shape_id),
                )
            )
    if not nodes:
        raise ValueError("PPTX has no supported visible text")
    return _build_document_units(source_version_id, nodes)


def _safe_ooxml_parts(content: bytes, *, required: set[str]) -> dict[str, bytes]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or len(infos) > _MAX_OOXML_PARTS
                or len(set(names)) != len(names)
                or any(
                    info.flag_bits & 1
                    or info.filename.startswith(("/", "\\"))
                    or ".." in info.filename.replace("\\", "/").split("/")
                    for info in infos
                )
                or sum(info.file_size for info in infos)
                > _MAX_OOXML_UNCOMPRESSED_BYTES
            ):
                raise ValueError("OOXML package violates the admitted bounds")
            if not required.issubset(names):
                raise ValueError("OOXML package is missing a required document part")
            lowered_names = {name.casefold() for name in names}
            if any(
                name.endswith(("vbaproject.bin", ".exe", ".dll"))
                or "/embeddings/" in name
                for name in lowered_names
            ):
                raise ValueError("OOXML executable or embedded content is forbidden")
            parts = {name: archive.read(name) for name in names}
    except BadZipFile as error:
        raise ValueError("OOXML package is invalid") from error
    for name, value in parts.items():
        if name.endswith((".xml", ".rels")) and (
            b"<!DOCTYPE" in value.upper() or b"<!ENTITY" in value.upper()
        ):
            raise ValueError("OOXML document type declarations are forbidden")
        if name.endswith(".rels"):
            relationships = _xml_root(value, "OOXML relationships")
            if any(
                relation.attrib.get("TargetMode", "").casefold() == "external"
                for relation in relationships.findall(
                    f".//{{{_RELATIONSHIP_NAMESPACE}}}Relationship"
                )
            ):
                raise ValueError("OOXML external relationships are forbidden")
    return parts


def _xml_root(content: bytes, label: str) -> Element:
    try:
        return fromstring(content)
    except ParseError as error:
        raise ValueError(f"{label} XML is invalid") from error


def _word_paragraph_text(paragraph: Element) -> str:
    fragments = [
        node.text or ""
        for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t")
    ]
    return " ".join("".join(fragments).split())


def _citation_payload(unit: DocumentEvidenceUnit) -> dict[str, object]:
    if isinstance(unit.citation_locator, PdfPageDocumentCitation):
        return {
            "kind": "pdf_page",
            "page_number": unit.citation_locator.page_number,
        }
    if isinstance(unit.citation_locator, DocxParagraphDocumentCitation):
        return {
            "kind": "docx_paragraph",
            "paragraph_number": unit.citation_locator.paragraph_number,
        }
    if isinstance(unit.citation_locator, DocxTableCellDocumentCitation):
        return {
            "kind": "docx_table_cell",
            "table_number": unit.citation_locator.table_number,
            "row_number": unit.citation_locator.row_number,
            "column_number": unit.citation_locator.column_number,
        }
    if isinstance(unit.citation_locator, PptxShapeDocumentCitation):
        return {
            "kind": "pptx_shape",
            "slide_number": unit.citation_locator.slide_number,
            "shape_id": unit.citation_locator.shape_id,
        }
    if isinstance(unit.citation_locator, HtmlDomDocumentCitation):
        return {
            "kind": "html_dom",
            "dom_path": unit.citation_locator.dom_path,
        }
    if isinstance(unit.citation_locator, OcrRegionDocumentCitation):
        return {
            "kind": "ocr_region",
            "page_number": unit.citation_locator.page_number,
            "bounding_box": {
                "x_min": unit.citation_locator.x_min,
                "y_min": unit.citation_locator.y_min,
                "x_max": unit.citation_locator.x_max,
                "y_max": unit.citation_locator.y_max,
            },
        }
    return {
        "kind": "text_lines",
        "start_line": unit.citation_locator.start_line,
        "end_line": unit.citation_locator.end_line,
    }


def _node_citation_payload(node: _ParsedDocumentNode) -> dict[str, object]:
    if node.page_number is not None:
        return {"kind": "pdf_page", "page_number": node.page_number}
    if node.docx_paragraph_number is not None:
        return {
            "kind": "docx_paragraph",
            "paragraph_number": node.docx_paragraph_number,
        }
    if node.docx_table_cell is not None:
        return {
            "kind": "docx_table_cell",
            "table_number": node.docx_table_cell[0],
            "row_number": node.docx_table_cell[1],
            "column_number": node.docx_table_cell[2],
        }
    if node.pptx_shape is not None:
        return {
            "kind": "pptx_shape",
            "slide_number": node.pptx_shape[0],
            "shape_id": node.pptx_shape[1],
        }
    if node.html_dom_path is not None:
        return {
            "kind": "html_dom",
            "dom_path": node.html_dom_path,
        }
    if node.ocr_region is not None:
        return {
            "kind": "ocr_region",
            "page_number": node.ocr_region[0],
            "bounding_box": {
                "x_min": node.ocr_region[1],
                "y_min": node.ocr_region[2],
                "x_max": node.ocr_region[3],
                "y_max": node.ocr_region[4],
            },
        }
    return {
        "kind": "text_lines",
        "start_line": node.start_line,
        "end_line": node.end_line,
    }


def _parse_text_lines(
    text: str,
    *,
    markdown: bool,
) -> list[_ParsedDocumentNode]:
    nodes: list[_ParsedDocumentNode] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        normalized = raw_line.strip()
        if not normalized:
            continue
        heading = markdown and raw_line.lstrip().startswith("#")
        node_text = normalized.lstrip("#").strip() if heading else normalized
        nodes.append(
            _ParsedDocumentNode(
                kind="heading" if heading else "paragraph",
                text=node_text,
                start_line=line_number,
                end_line=line_number,
            )
        )
    return nodes


class _SafeHtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[_ParsedDocumentNode] = []
        self._blocks: list[_OpenHtmlBlock] = []
        self._elements: list[_OpenHtmlElement] = []
        self._root_child_counts: dict[str, int] = {}
        self._suppressed_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        normalized = tag.casefold()
        dom_path = self._open_element(normalized)
        if normalized in _HTML_SUPPRESSED_TAGS:
            self._suppressed_depth += 1
            return
        if normalized == "br" and not self._suppressed_depth and self._blocks:
            self._blocks[-1].fragments.append(" ")
        if self._suppressed_depth or normalized not in _HTML_BLOCK_TAGS:
            return
        self._blocks.append(
            _OpenHtmlBlock(
                tag=normalized,
                kind="heading" if normalized.startswith("h") else "paragraph",
                start_line=self.getpos()[0],
                fragments=[],
                dom_path=dom_path,
            )
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in _HTML_SUPPRESSED_TAGS:
            if self._suppressed_depth:
                self._suppressed_depth -= 1
            self._close_element(normalized)
            return
        if not self._suppressed_depth and self._blocks:
            if self._blocks[-1].tag == normalized:
                self._close_block(self.getpos()[0])
        self._close_element(normalized)

    def _open_element(self, tag: str) -> str:
        child_counts = (
            self._elements[-1].child_counts
            if self._elements
            else self._root_child_counts
        )
        child_counts[tag] = child_counts.get(tag, 0) + 1
        parent_path = self._elements[-1].dom_path if self._elements else ""
        dom_path = f"{parent_path}/{tag}[{child_counts[tag]}]"
        if tag not in _HTML_VOID_TAGS:
            self._elements.append(
                _OpenHtmlElement(tag=tag, dom_path=dom_path, child_counts={})
            )
        return dom_path

    def _close_element(self, tag: str) -> None:
        matching_index = next(
            (
                index
                for index in range(len(self._elements) - 1, -1, -1)
                if self._elements[index].tag == tag
            ),
            None,
        )
        if matching_index is None:
            return
        del self._elements[matching_index:]

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth and self._blocks:
            self._blocks[-1].fragments.append(data)

    def finish(self, end_line: int) -> list[_ParsedDocumentNode]:
        while self._blocks:
            self._close_block(end_line)
        return self.nodes

    def _close_block(self, end_line: int) -> None:
        block = self._blocks.pop()
        text = " ".join("".join(block.fragments).split())
        if text:
            self.nodes.append(
                _ParsedDocumentNode(
                    kind=block.kind,
                    text=text,
                    start_line=block.start_line,
                    end_line=max(block.start_line, end_line),
                    html_dom_path=block.dom_path,
                )
            )


def _parse_html(text: str) -> list[_ParsedDocumentNode]:
    parser = _SafeHtmlTextExtractor()
    parser.feed(text)
    parser.close()
    nodes = parser.finish(max(1, len(text.splitlines())))
    return sorted(nodes, key=lambda node: (node.start_line, node.end_line))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validate_authority_id(value: str, field: str) -> None:
    if _AUTHORITY_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is not a valid opaque authority identifier")
