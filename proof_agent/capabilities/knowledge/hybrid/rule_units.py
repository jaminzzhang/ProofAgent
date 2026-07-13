"""Deterministic projection of canonical insurance documents into reviewable rule units."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Literal, Self
from urllib.parse import quote

from pydantic import ConfigDict, Field, StrictInt, StrictStr, StringConstraints, model_validator

from proof_agent.capabilities.knowledge.hybrid.canonicalizer import (
    validate_page_geometry_and_bounds,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredTable,
    StructuredTableCell,
)
from proof_agent.contracts.insurance_rules import (
    InsuranceRuleCellCoordinate,
    InsuranceRuleMetadataDraft,
    InsuranceRulePageBoundingBox,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RuleUnitKind = Literal["document", "clause", "section", "table_row", "row_group"]

_ENGLISH_DEFINITION_STATEMENT = re.compile(
    r"""
    ^\s*
    (?:["“](?P<quoted>[^"”\r\n]{1,127})["”]
      |(?P<plain>[A-Za-z][A-Za-z0-9 _-]{0,126}?))
    (?:\s*[:：,，]\s*|\s+)
    (?:means|is\s+defined\s+as|refers\s+to)\s+
    (?P<body>\S.*?)\s*$
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
_CHINESE_SUOCHENG_DEFINITION_STATEMENT = re.compile(
    r"""
    ^\s*[^，。；：:\r\n]{0,32}?所称\s*
    (?:["“](?P<quoted>[^"”\r\n]{1,64})["”]
      |(?P<plain>[A-Za-z0-9\u3400-\u9fff·_-]{1,64}))
    \s*[:：,，]?\s*(?:是指|系指|定义为)\s*
    (?P<body>\S.*?)\s*$
    """,
    re.DOTALL | re.VERBOSE,
)
_CHINESE_SUOCHENG_DEFINITION_CANDIDATE = re.compile(
    r"^\s*[^，。；：:\r\n]{0,32}?所称[\s\S]*?(?:是指|系指|定义为)",
)
_SUOCHENG_UNQUOTED_CONJUNCTIONS = ("以及", "及", "和", "与", "或")
_CHINESE_DEFINITION_STATEMENT = re.compile(
    r"""
    ^\s*
    (?:["“](?P<quoted>[^"”\r\n]{1,64})["”]
      |(?P<plain>[^，。；：:\s][^，。；：:\r\n]{0,63}?))
    \s*[:：,，]?\s*(?:是指|系指|定义为)\s*
    (?P<body>\S.*?)\s*$
    """,
    re.DOTALL | re.VERBOSE,
)
_CHINESE_QUOTED_BARE_ZHI_DEFINITION_STATEMENT = re.compile(
    r"""
    ^\s*
    ["“](?P<quoted>[^"”\r\n]{1,64})["”]\s*[:：,，]?\s*指\s*
    (?P<body>\S.*?)\s*$
    """,
    re.DOTALL | re.VERBOSE,
)
_CHINESE_UNQUOTED_BARE_ZHI_DEFINITION_STATEMENT = re.compile(
    r"""
    ^\s*
    (?P<plain>[^，。；：:\s][^，。；：:\r\n]{0,63}?)\s*[:：,，]\s*指\s*
    (?P<body>\S.*?)\s*$
    """,
    re.DOTALL | re.VERBOSE,
)
_AMBIGUOUS_BARE_ZHI_CONTINUATIONS = frozenset(
    {
        "向",
        "出",
        "示",
        "导",
        "定",
        "派",
        "令",
        "引",
        "控",
        "责",
        "挥",
        "明",
        "代",
        "标",
        "数",
        "针",
        "纹",
        "甲",
        "摘",
        "认",
        "望",
        "教",
    }
)
_DEFINITION_CONTENT_BLOCK_TYPES = frozenset({"paragraph", "list_item"})


class _RuleProjectionModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RuleUnitProjectionReviewRequired(ValueError):
    """Canonical structure cannot form a coherent authority unit without human review."""


class RuleUnitProjectionLimits(_RuleProjectionModel):
    max_pages: PositiveInt = 500
    max_blocks: PositiveInt = 100_000
    max_tables: PositiveInt = 10_000
    max_cells: PositiveInt = 250_000
    max_units: PositiveInt = 100_000
    max_text_characters: PositiveInt = 50_000_000
    max_unit_output_characters: PositiveInt = 5_000_000
    max_document_output_characters: PositiveInt = 50_000_000
    max_work_units: PositiveInt = 5_000_000


@dataclass(slots=True)
class RuleUnitProjectionWorkCounter:
    """Deterministic operation counter used to enforce projection work bounds."""

    max_work_units: int
    used: int = 0

    def __post_init__(self) -> None:
        if type(self.max_work_units) is not int or self.max_work_units <= 0:
            raise ValueError("max_work_units must be a positive integer")
        if type(self.used) is not int or not 0 <= self.used <= self.max_work_units:
            raise ValueError("used work units must be within the configured limit")

    def consume(self, amount: int) -> None:
        if type(amount) is not int or amount < 0:
            raise ValueError("projection work amount must be a nonnegative integer")
        self.used += amount
        if self.used > self.max_work_units:
            raise RuleUnitProjectionReviewRequired("rule-unit projection work budget exceeded")


DEFAULT_RULE_UNIT_PROJECTION_LIMITS = RuleUnitProjectionLimits()


@dataclass(slots=True)
class _ProjectionOutputBudget:
    max_unit_characters: int
    max_document_characters: int
    work: RuleUnitProjectionWorkCounter
    used: int = 0

    def preflight_content(self, character_count: int) -> None:
        """Reject and charge a content allocation before constructing its string."""

        self._check(character_count)
        self.work.consume(character_count)

    def commit_unit(self, character_count: int, *, precharged: int) -> None:
        if precharged > character_count:
            raise ValueError("precharged output cannot exceed unit output")
        self._check(character_count)
        self.used += character_count

    def _check(self, character_count: int) -> None:
        if character_count > self.max_unit_characters:
            raise RuleUnitProjectionReviewRequired(
                "projected rule-unit output characters exceed the limit"
            )
        if self.used + character_count > self.max_document_characters:
            raise RuleUnitProjectionReviewRequired(
                "projected document output characters exceed the limit"
            )


PageBoundingBox = InsuranceRulePageBoundingBox
RuleCellCoordinate = InsuranceRuleCellCoordinate


class InsuranceRuleUnitDraft(_RuleProjectionModel):
    """Non-authoritative, structurally coherent rule unit awaiting business approval."""

    ordinal: NonNegativeInt
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_sha256: Sha256
    structured_build_id: NonBlankStr
    structured_build_identity: StructuredArtifactBuildIdentity
    logical_rule_key: NonBlankStr
    unit_kind: RuleUnitKind
    content: NonBlankStr
    citation_uri: NonBlankStr
    heading_path: tuple[NonBlankStr, ...] = ()
    definitions: tuple[NonBlankStr, ...] = ()
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1)
    page_bboxes: tuple[PageBoundingBox, ...] = Field(min_length=1)
    block_ids: tuple[NonBlankStr, ...] = ()
    table_id: NonBlankStr | None = None
    table_continuation_id: NonBlankStr | None = None
    table_title: NonBlankStr | None = None
    table_headers: tuple[NonBlankStr, ...] = ()
    table_context: StrictStr = ""
    row_header: StrictStr | None = None
    row_numbers: tuple[NonNegativeInt, ...] = ()
    header_cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    inherited_metadata: InsuranceRuleMetadataDraft

    @model_validator(mode="after")
    def validate_lineage_and_shape(self) -> Self:
        if self.structured_build_id != self.structured_build_identity.build_id:
            raise ValueError("structured build id must match its exact build identity")
        if self.original_sha256 != self.structured_build_identity.source_sha256:
            raise ValueError("original SHA must match the structured build identity")
        if (
            self.inherited_metadata.document_id != self.document_id
            or self.inherited_metadata.revision_id != self.revision_id
        ):
            raise ValueError("inherited metadata draft lineage must match the rule unit")
        if tuple(sorted(set(self.page_numbers))) != self.page_numbers:
            raise ValueError("page_numbers must be strictly increasing and unique")
        if tuple(sorted(set(self.row_numbers))) != self.row_numbers:
            raise ValueError("row_numbers must be strictly increasing and unique")
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("block_ids must be unique")
        bbox_pages = tuple(item.page_number for item in self.page_bboxes)
        if tuple(sorted(set(bbox_pages))) != bbox_pages:
            raise ValueError("page_bboxes must contain one region per page in page order")
        if set(bbox_pages) != set(self.page_numbers):
            raise ValueError("page_bboxes must cover exactly the projected page_numbers")
        if len(self.definitions) != len(set(self.definitions)):
            raise ValueError("definition context must be unique and deterministic")
        table_kind = self.unit_kind in {"table_row", "row_group"}
        table_fields_present = any(
            (
                self.table_id is not None,
                self.table_continuation_id is not None,
                self.table_title is not None,
                bool(self.table_headers),
                bool(self.table_context),
                self.row_header is not None,
                bool(self.row_numbers),
                bool(self.header_cell_coordinates),
                bool(self.cell_coordinates),
            )
        )
        if table_kind:
            if (
                self.table_id is None
                or self.row_header is None
                or not self.table_context
                or not self.row_numbers
            ):
                raise ValueError("table rule units require table context and row lineage")
            if not self.cell_coordinates:
                raise ValueError("table rule units require complete cell coordinates")
            if len(self.cell_coordinates) < 2:
                raise ValueError("table rule units require coherent multi-cell evidence")
            if len({coordinate.column for coordinate in self.cell_coordinates}) < 2:
                raise ValueError("table rule units require row-header and data columns")
            if self.block_ids:
                raise ValueError("table rule units cannot claim block lineage")
            if self.unit_kind == "table_row" and len(self.row_numbers) != 1:
                raise ValueError("table_row requires exactly one row number")
            if self.unit_kind == "row_group" and len(self.row_numbers) < 2:
                raise ValueError("row_group requires at least two row numbers")
            if self.table_continuation_id == self.table_id:
                raise ValueError("a table rule unit cannot continue itself")
            page_regions = {item.page_number: item.bbox for item in self.page_bboxes}
            all_coordinates = (*self.header_cell_coordinates, *self.cell_coordinates)
            coordinate_keys = [
                (item.page_number, item.row, item.column) for item in all_coordinates
            ]
            if len(coordinate_keys) != len(set(coordinate_keys)):
                raise ValueError("table cell coordinate anchors must be unique")
            for coordinate in all_coordinates:
                region = page_regions.get(coordinate.page_number)
                if region is None or not _bbox_contains(region, coordinate.bbox):
                    raise ValueError("table cell coordinates must stay within rule-unit geometry")
            covered_intervals = _merge_integer_intervals(
                (
                    (coordinate.row, coordinate.row + coordinate.row_span - 1)
                    for coordinate in self.cell_coordinates
                ),
                merge_adjacent=True,
            )
            if covered_intervals != _integer_intervals(self.row_numbers):
                raise ValueError("data cell coordinates must cover exactly the projected rows")
        elif table_fields_present:
            raise ValueError("non-table rule units cannot contain table lineage")
        return self


def project_rule_units(
    artifact: StructuredKnowledgeDocumentArtifact,
    *,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str,
    limits: RuleUnitProjectionLimits = DEFAULT_RULE_UNIT_PROJECTION_LIMITS,
    work_counter: RuleUnitProjectionWorkCounter | None = None,
) -> tuple[InsuranceRuleUnitDraft, ...]:
    """Project business-reviewable structural units; never split by token count or cell."""

    if work_counter is None:
        work_counter = RuleUnitProjectionWorkCounter(limits.max_work_units)
    elif work_counter.max_work_units > limits.max_work_units:
        raise ValueError("work counter cannot exceed the projection limit")
    _validate_projection_inputs(
        artifact,
        document_defaults=document_defaults,
        source_id=source_id,
        limits=limits,
        work=work_counter,
    )
    output = _ProjectionOutputBudget(
        max_unit_characters=limits.max_unit_output_characters,
        max_document_characters=limits.max_document_output_characters,
        work=work_counter,
    )
    source_id = source_id.strip()
    definitions = _build_definition_index(artifact.pages, work=work_counter)
    block_candidates = _project_blocks(
        artifact.pages,
        definitions=definitions,
        work=work_counter,
        output=output,
    )
    table_candidates = _project_tables(
        artifact.pages,
        definitions=definitions,
        work=work_counter,
        output=output,
    )
    candidates = sorted(
        (*block_candidates, *table_candidates),
        key=lambda item: item.sort_key,
    )
    if not candidates:
        raise ValueError("canonical artifact contains no coherent rule units")
    if len(candidates) > limits.max_units:
        raise RuleUnitProjectionReviewRequired("projected rule-unit count exceeds the limit")
    work_counter.consume(len(candidates))
    units = tuple(
        _draft_from_candidate(
            artifact,
            candidate,
            ordinal=ordinal,
            document_defaults=document_defaults,
            source_id=source_id,
        )
        for ordinal, candidate in enumerate(candidates)
    )
    logical_keys = [unit.logical_rule_key for unit in units]
    if len(logical_keys) != len(set(logical_keys)):
        raise ValueError("projected logical rule keys must be unique")
    return units


class _ProjectionCandidate(_RuleProjectionModel):
    sort_key: tuple[PositiveInt, NonNegativeInt, NonNegativeInt, NonBlankStr]
    unit_kind: RuleUnitKind
    content: NonBlankStr
    heading_path: tuple[NonBlankStr, ...]
    definitions: tuple[NonBlankStr, ...]
    page_numbers: tuple[PositiveInt, ...]
    page_bboxes: tuple[PageBoundingBox, ...]
    block_ids: tuple[NonBlankStr, ...] = ()
    anchor_parts: tuple[NonBlankStr, ...]
    table_id: NonBlankStr | None = None
    table_continuation_id: NonBlankStr | None = None
    table_title: NonBlankStr | None = None
    table_headers: tuple[NonBlankStr, ...] = ()
    table_context: StrictStr = ""
    row_header: StrictStr | None = None
    row_numbers: tuple[NonNegativeInt, ...] = ()
    header_cell_coordinates: tuple[RuleCellCoordinate, ...] = ()
    cell_coordinates: tuple[RuleCellCoordinate, ...] = ()


def _validate_projection_inputs(
    artifact: StructuredKnowledgeDocumentArtifact,
    *,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str,
    limits: RuleUnitProjectionLimits,
    work: RuleUnitProjectionWorkCounter,
) -> None:
    # Revalidation closes model_copy/construct bypasses before identity material is produced.
    artifact = StructuredKnowledgeDocumentArtifact.model_validate(artifact.model_dump())
    document_defaults = InsuranceRuleMetadataDraft.model_validate(document_defaults.model_dump())
    if (
        document_defaults.document_id != artifact.document_id
        or document_defaults.revision_id != artifact.revision_id
    ):
        raise ValueError("metadata draft lineage must match the canonical artifact")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must be an explicit non-empty string")
    if len(artifact.pages) > limits.max_pages:
        raise RuleUnitProjectionReviewRequired("canonical page count exceeds projection limits")
    page_numbers = tuple(page.page_number for page in artifact.pages)
    if tuple(sorted(set(page_numbers))) != page_numbers:
        raise ValueError("canonical page numbers must be strictly increasing and unique")
    prior_table_ids: set[str] = set()
    seen_block_ids: set[str] = set()
    seen_table_ids: set[str] = set()
    total_blocks = 0
    total_tables = 0
    total_cells = 0
    total_text = 0
    for page in artifact.pages:
        work.consume(1 + len(page.blocks) + len(page.tables))
        validate_page_geometry_and_bounds(page)
        total_blocks += len(page.blocks)
        total_tables += len(page.tables)
        page_cell_count = sum(len(table.cells) for table in page.tables)
        total_cells += page_cell_count
        work.consume(page_cell_count)
        total_text += sum(len(block.text) for block in page.blocks)
        total_text += sum(
            len(table.title or "") + sum(len(cell.text) for cell in table.cells)
            for table in page.tables
        )
        block_ids = {block.block_id for block in page.blocks}
        table_ids = {table.table_id for table in page.tables}
        if len(block_ids) != len(page.blocks) or block_ids & seen_block_ids:
            raise ValueError("canonical block identities must be document-unique")
        if len(table_ids) != len(page.tables) or table_ids & seen_table_ids:
            raise ValueError("canonical table identities must be document-unique")
        orders = tuple(block.reading_order for block in page.blocks)
        if len(orders) != len(set(orders)) or tuple(sorted(orders)) != orders:
            raise ValueError("canonical block reading order must be strictly increasing and unique")
        for table in page.tables:
            if table.continuation_of is not None and table.continuation_of not in prior_table_ids:
                raise ValueError("table continuation must reference an earlier canonical table")
            grid_anchors = [(cell.row, cell.column) for cell in table.cells]
            if len(grid_anchors) != len(set(grid_anchors)):
                raise ValueError("canonical table cell anchors must be unique")
        seen_block_ids.update(block_ids)
        seen_table_ids.update(table_ids)
        prior_table_ids.update(table_ids)
    if (
        total_blocks > limits.max_blocks
        or total_tables > limits.max_tables
        or total_cells > limits.max_cells
        or total_text > limits.max_text_characters
    ):
        raise RuleUnitProjectionReviewRequired("canonical document exceeds projection limits")


@dataclass(frozen=True, slots=True)
class _DefinitionEntry:
    term: str
    normalized_term: str
    text: str
    block_id: str


@dataclass(frozen=True, slots=True)
class _DefinitionIndex:
    entries: tuple[_DefinitionEntry, ...]

    def resolve(
        self,
        text: str,
        *,
        work: RuleUnitProjectionWorkCounter,
    ) -> tuple[str, ...]:
        matched: list[str] = []
        by_term: dict[str, list[_DefinitionEntry]] = {}
        for entry in self.entries:
            work.consume(1 + len(text) // max(1, len(entry.term)))
            if _references_term(text, entry.term):
                by_term.setdefault(entry.normalized_term, []).append(entry)
        matched_terms = sorted(by_term)
        for index, left in enumerate(matched_terms):
            for right in matched_terms[index + 1 :]:
                if left in right or right in left:
                    raise RuleUnitProjectionReviewRequired(
                        "definition reference matches overlapping ambiguous terms"
                    )
        for normalized_term in sorted(by_term):
            entries = by_term[normalized_term]
            if len(entries) != 1:
                raise RuleUnitProjectionReviewRequired(
                    "referenced definition term has ambiguous duplicate definitions"
                )
            matched.append(entries[0].text)
        return tuple(matched)


def _build_definition_index(
    pages: tuple[StructuredPage, ...],
    *,
    work: RuleUnitProjectionWorkCounter,
) -> _DefinitionIndex:
    entries: list[_DefinitionEntry] = []
    for page in pages:
        for block in page.blocks:
            if block.block_type not in _DEFINITION_CONTENT_BLOCK_TYPES or not block.text.strip():
                continue
            work.consume(1 + len(block.text) // 64)
            term = _definition_term(block.text)
            if term is None:
                continue
            entries.append(
                _DefinitionEntry(
                    term=term,
                    normalized_term=term.casefold(),
                    text=block.text.strip(),
                    block_id=block.block_id,
                )
            )
    entries.sort(key=lambda item: (item.normalized_term, item.block_id))
    work.consume(_sort_work(len(entries)))
    return _DefinitionIndex(entries=tuple(entries))


def _definition_term(text: str) -> str | None:
    suocheng = _CHINESE_SUOCHENG_DEFINITION_STATEMENT.fullmatch(text)
    if suocheng is not None:
        quoted = suocheng.group("quoted")
        if quoted is not None:
            return quoted.strip()
        plain = suocheng.group("plain").strip()
        if any(marker in plain for marker in _SUOCHENG_UNQUOTED_CONJUNCTIONS):
            raise RuleUnitProjectionReviewRequired(
                "unquoted 所称 definition term contains ambiguous conjunction markers"
            )
        return plain
    if _CHINESE_SUOCHENG_DEFINITION_CANDIDATE.match(text) is not None:
        raise RuleUnitProjectionReviewRequired(
            "所称 definition statement does not expose one reliably bounded term"
        )
    for pattern in (
        _ENGLISH_DEFINITION_STATEMENT,
        _CHINESE_DEFINITION_STATEMENT,
        _CHINESE_QUOTED_BARE_ZHI_DEFINITION_STATEMENT,
    ):
        match = pattern.fullmatch(text)
        if match is not None:
            term = match.group("quoted") or match.group("plain")
            term = term.strip()
            if term:
                return term
    unquoted_bare_zhi = _CHINESE_UNQUOTED_BARE_ZHI_DEFINITION_STATEMENT.fullmatch(text)
    if unquoted_bare_zhi is not None:
        body = unquoted_bare_zhi.group("body")
        if body[0] in _AMBIGUOUS_BARE_ZHI_CONTINUATIONS:
            raise RuleUnitProjectionReviewRequired(
                "unquoted bare 指 statement has an ambiguous compound-verb continuation"
            )
        term = unquoted_bare_zhi.group("plain").strip()
        if term:
            return term
    return None


def _references_term(text: str, term: str) -> bool:
    if term.isascii():
        return (
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(term)}(?:s)?(?![A-Za-z0-9_])",
                text,
                re.IGNORECASE,
            )
            is not None
        )
    return term in text


def _project_blocks(
    pages: tuple[StructuredPage, ...],
    *,
    definitions: _DefinitionIndex,
    work: RuleUnitProjectionWorkCounter,
    output: _ProjectionOutputBudget,
) -> tuple[_ProjectionCandidate, ...]:
    ordered = tuple((page, block) for page in pages for block in page.blocks)
    candidates: list[_ProjectionCandidate] = []
    index = 0
    while index < len(ordered):
        page, block = ordered[index]
        if block.block_type != "heading":
            if block.block_type in {"paragraph", "list_item"} and block.text.strip():
                work.consume(1)
                candidates.append(
                    _block_candidate(
                        page,
                        block,
                        definitions=definitions,
                        unit_kind="clause",
                        work=work,
                        output=output,
                    )
                )
            index += 1
            continue

        section_blocks = [block]
        cursor = index + 1
        while cursor < len(ordered) and ordered[cursor][1].block_type != "heading":
            _, candidate = ordered[cursor]
            if candidate.block_type not in {"header", "footer"} and candidate.text.strip():
                section_blocks.append(candidate)
            cursor += 1
        if len(section_blocks) > 1:
            work.consume(1)
            candidates.append(
                _section_candidate(
                    ordered[index:cursor],
                    section_blocks,
                    definitions,
                    work=work,
                    output=output,
                )
            )
        index += 1
    return tuple(candidates)


def _block_candidate(
    page: StructuredPage,
    block: StructuredBlock,
    *,
    definitions: _DefinitionIndex,
    unit_kind: Literal["clause"],
    work: RuleUnitProjectionWorkCounter,
    output: _ProjectionOutputBudget,
) -> _ProjectionCandidate:
    content = block.text.strip()
    output.preflight_content(len(content))
    resolved_definitions = definitions.resolve(content, work=work)
    candidate = _ProjectionCandidate(
        sort_key=(page.page_number, block.reading_order, 1, block.block_id),
        unit_kind=unit_kind,
        content=content,
        heading_path=block.heading_path,
        definitions=resolved_definitions,
        page_numbers=(page.page_number,),
        page_bboxes=(PageBoundingBox(page_number=page.page_number, bbox=block.bbox),),
        block_ids=(block.block_id,),
        anchor_parts=(block.block_id,),
    )
    output.commit_unit(
        _candidate_output_characters(candidate),
        precharged=len(content),
    )
    return candidate


def _section_candidate(
    ordered_slice: tuple[tuple[StructuredPage, StructuredBlock], ...],
    blocks: list[StructuredBlock],
    definitions: _DefinitionIndex,
    *,
    work: RuleUnitProjectionWorkCounter,
    output: _ProjectionOutputBudget,
) -> _ProjectionCandidate:
    heading = blocks[0]
    included_block_ids = {block.block_id for block in blocks}
    included = [
        (page, block) for page, block in ordered_slice if block.block_id in included_block_ids
    ]
    page_numbers = tuple(dict.fromkeys(page.page_number for page, _ in included))
    page_bboxes = tuple(
        PageBoundingBox(
            page_number=page_number,
            bbox=_union_bbox(
                block.bbox for page, block in included if page.page_number == page_number
            ),
        )
        for page_number in page_numbers
    )
    content_parts = tuple(block.text.strip() for block in blocks)
    content_characters = sum(map(len, content_parts)) + len(content_parts) - 1
    output.preflight_content(content_characters)
    content = "\n".join(content_parts)
    resolved_definitions = definitions.resolve(content, work=work)
    candidate = _ProjectionCandidate(
        sort_key=(ordered_slice[0][0].page_number, heading.reading_order, 0, heading.block_id),
        unit_kind="section",
        content=content,
        heading_path=heading.heading_path or (heading.text.strip(),),
        definitions=resolved_definitions,
        page_numbers=page_numbers,
        page_bboxes=page_bboxes,
        block_ids=tuple(block.block_id for block in blocks),
        anchor_parts=(heading.block_id,),
    )
    output.commit_unit(
        _candidate_output_characters(candidate),
        precharged=content_characters,
    )
    return candidate


def _project_tables(
    pages: tuple[StructuredPage, ...],
    *,
    definitions: _DefinitionIndex,
    work: RuleUnitProjectionWorkCounter,
    output: _ProjectionOutputBudget,
) -> tuple[_ProjectionCandidate, ...]:
    candidates: list[_ProjectionCandidate] = []
    heading_paths = _resolve_table_heading_paths(pages, work=work)
    for page in pages:
        for table_index, table in enumerate(page.tables):
            candidates.extend(
                _table_candidates(
                    page,
                    table,
                    table_index=table_index,
                    heading_path=heading_paths[table.table_id],
                    definitions=definitions,
                    work=work,
                    output=output,
                )
            )
    return tuple(candidates)


def _resolve_table_heading_paths(
    pages: tuple[StructuredPage, ...],
    *,
    work: RuleUnitProjectionWorkCounter,
) -> dict[str, tuple[str, ...]]:
    resolved: dict[str, tuple[str, ...]] = {}
    prior_page_heading: tuple[str, ...] | None = None
    for page in pages:
        headings = tuple(block for block in page.blocks if block.block_type == "heading")
        tables = tuple(
            sorted(page.tables, key=lambda table: (table.bbox.y0, table.bbox.x0, table.table_id))
        )
        work.consume(len(headings) + _sort_work(len(tables)))
        for table in tables:
            if table.continuation_of is not None:
                inherited = resolved.get(table.continuation_of)
                if inherited is None:
                    raise RuleUnitProjectionReviewRequired(
                        "table continuation has no resolved parent heading context"
                    )
                resolved[table.table_id] = inherited
                continue
            work.consume(len(headings))
            preceding = tuple(
                heading
                for heading in headings
                if heading.bbox.y1 <= table.bbox.y0
                and _horizontal_overlap(heading.bbox, table.bbox)
            )
            if preceding:
                nearest_edge = max(heading.bbox.y1 for heading in preceding)
                nearest = tuple(heading for heading in preceding if heading.bbox.y1 == nearest_edge)
                paths = {
                    heading.heading_path or (heading.text.strip(),)
                    for heading in nearest
                    if heading.text.strip()
                }
                if len(paths) != 1:
                    raise RuleUnitProjectionReviewRequired(
                        "table heading association is geometrically ambiguous"
                    )
                resolved[table.table_id] = next(iter(paths))
            elif prior_page_heading is not None:
                resolved[table.table_id] = prior_page_heading
            else:
                raise RuleUnitProjectionReviewRequired(
                    "table has no reliable preceding heading association"
                )
        if headings:
            final = max(headings, key=lambda heading: heading.reading_order)
            if not final.text.strip():
                raise RuleUnitProjectionReviewRequired("page heading context is empty")
            prior_page_heading = final.heading_path or (final.text.strip(),)
    return resolved


def _horizontal_overlap(left: BoundingBox, right: BoundingBox) -> bool:
    return min(left.x1, right.x1) > max(left.x0, right.x0)


@dataclass(frozen=True, slots=True)
class _IndexedRowGroup:
    row_numbers: tuple[int, ...]
    cells: tuple[StructuredTableCell, ...]


@dataclass(frozen=True, slots=True)
class _TableCellIndex:
    header_cells: tuple[StructuredTableCell, ...]
    row_groups: tuple[_IndexedRowGroup, ...]


def _table_candidates(
    page: StructuredPage,
    table: StructuredTable,
    *,
    table_index: int,
    heading_path: tuple[str, ...],
    definitions: _DefinitionIndex,
    work: RuleUnitProjectionWorkCounter,
    output: _ProjectionOutputBudget,
) -> tuple[_ProjectionCandidate, ...]:
    index = _build_table_cell_index(table, work=work)
    if not index.row_groups:
        return ()
    header_cells = index.header_cells
    table_title = table.title.strip() if table.title and table.title.strip() else None
    table_headers = tuple(cell.text.strip() for cell in header_cells)
    table_context = _table_context(table, header_cells)
    candidates: list[_ProjectionCandidate] = []
    for group_index, row_group in enumerate(index.row_groups):
        work.consume(1)
        row_numbers = row_group.row_numbers
        data_cells = row_group.cells
        first_column = min(cell.column for cell in data_cells)
        row_headers = tuple(
            dict.fromkeys(
                cell.text.strip()
                for cell in data_cells
                if cell.column == first_column and cell.text.strip()
            )
        )
        row_header = " | ".join(row_headers) or None
        content_parts, content_characters = _table_group_content_parts(data_cells)
        output.preflight_content(content_characters)
        content = _table_group_content(content_parts)
        definition_context = "\n".join((content, table_context))
        unit_kind: Literal["table_row", "row_group"] = (
            "row_group" if len(row_numbers) > 1 else "table_row"
        )
        candidate = _ProjectionCandidate(
            sort_key=(page.page_number, 1_000_000 + table_index, group_index, table.table_id),
            unit_kind=unit_kind,
            content=content,
            heading_path=heading_path,
            definitions=definitions.resolve(definition_context, work=work),
            page_numbers=(page.page_number,),
            page_bboxes=(
                PageBoundingBox(
                    page_number=page.page_number,
                    bbox=table.bbox,
                ),
            ),
            anchor_parts=(
                table.table_id,
                "rows-" + "-".join(str(row) for row in row_numbers),
            ),
            table_id=table.table_id,
            table_continuation_id=table.continuation_of,
            table_title=table_title,
            table_headers=table_headers,
            table_context=table_context,
            row_header=row_header,
            row_numbers=row_numbers,
            header_cell_coordinates=tuple(
                _cell_coordinate(page.page_number, cell) for cell in header_cells
            ),
            cell_coordinates=tuple(_cell_coordinate(page.page_number, cell) for cell in data_cells),
        )
        output.commit_unit(
            _candidate_output_characters(candidate),
            precharged=content_characters,
        )
        candidates.append(candidate)
    return tuple(candidates)


def _build_table_cell_index(
    table: StructuredTable,
    *,
    work: RuleUnitProjectionWorkCounter,
) -> _TableCellIndex:
    _validate_table_occupancy(table.cells, work=work)
    nonempty = tuple(cell for cell in table.cells if cell.text.strip())
    work.consume(len(table.cells))
    if not nonempty:
        return _TableCellIndex(header_cells=(), row_groups=())
    rows = _covered_grid_rows(nonempty)
    work.consume(len(rows))
    header_rows: tuple[int, ...]
    data_rows: tuple[int, ...]
    if len(rows) == 1:
        header_rows = ()
        data_rows = rows
    else:
        header_rows = (rows[0],)
        data_rows = rows[1:]
    header_cells = tuple(
        sorted(
            (cell for cell in nonempty if cell.row in header_rows),
            key=lambda cell: (cell.row, cell.column),
        )
    )
    if any(cell.row_span != 1 for cell in header_cells):
        raise RuleUnitProjectionReviewRequired(
            "table header spans data rows and requires structural review"
        )
    data_cells = tuple(cell for cell in nonempty if cell.row not in header_rows)
    row_groups = _structural_row_groups(data_rows, data_cells, work=work)
    row_to_group = {
        row: group_index
        for group_index, row_numbers in enumerate(row_groups)
        for row in row_numbers
    }
    indexed_cells: list[list[StructuredTableCell]] = [[] for _ in row_groups]
    for cell in data_cells:
        group_index = row_to_group.get(cell.row)
        if group_index is None:
            raise RuleUnitProjectionReviewRequired("data cell has no structural row group")
        indexed_cells[group_index].append(cell)
    indexed_groups: list[_IndexedRowGroup] = []
    for row_numbers, cells in zip(row_groups, indexed_cells, strict=True):
        ordered_cells = tuple(sorted(cells, key=lambda cell: (cell.row, cell.column)))
        if len(ordered_cells) < 2 or len({cell.column for cell in ordered_cells}) < 2:
            raise RuleUnitProjectionReviewRequired(
                "table contains an isolated cell without canonical row-group structure"
            )
        indexed_groups.append(_IndexedRowGroup(row_numbers=row_numbers, cells=ordered_cells))
    work.consume(len(data_cells) + len(data_rows) + _sort_work(len(data_cells)))
    return _TableCellIndex(header_cells=header_cells, row_groups=tuple(indexed_groups))


def _structural_row_groups(
    data_rows: tuple[int, ...],
    cells: tuple[StructuredTableCell, ...],
    *,
    work: RuleUnitProjectionWorkCounter,
) -> tuple[tuple[int, ...], ...]:
    if not data_rows:
        return ()
    intervals = [(row, row) for row in data_rows]
    intervals.extend(
        (cell.row, cell.row + cell.row_span - 1)
        for cell in cells
        if cell.row <= data_rows[-1] and cell.row + cell.row_span - 1 >= data_rows[0]
    )
    merged = _merge_integer_intervals(intervals)
    work.consume(len(intervals) + _sort_work(len(intervals)))
    groups: list[tuple[int, ...]] = []
    row_index = 0
    for start, end in merged:
        group: list[int] = []
        while row_index < len(data_rows) and data_rows[row_index] < start:
            row_index += 1
        while row_index < len(data_rows) and data_rows[row_index] <= end:
            group.append(data_rows[row_index])
            row_index += 1
        if group:
            groups.append(tuple(group))
    return tuple(groups)


class _RangeMaxTree:
    def __init__(self, segment_count: int) -> None:
        size = 1
        while size < segment_count:
            size *= 2
        self._size = size
        self._maximum = [0] * (2 * size)
        self._lazy = [0] * (2 * size)

    def add(self, left: int, right: int, delta: int) -> None:
        self._add(left, right, delta, 1, 0, self._size)

    def maximum(self, left: int, right: int) -> int:
        return self._query(left, right, 1, 0, self._size)

    def _add(
        self,
        left: int,
        right: int,
        delta: int,
        node: int,
        node_left: int,
        node_right: int,
    ) -> None:
        if right <= node_left or node_right <= left:
            return
        if left <= node_left and node_right <= right:
            self._maximum[node] += delta
            self._lazy[node] += delta
            return
        middle = (node_left + node_right) // 2
        self._add(left, right, delta, node * 2, node_left, middle)
        self._add(left, right, delta, node * 2 + 1, middle, node_right)
        self._maximum[node] = self._lazy[node] + max(
            self._maximum[node * 2], self._maximum[node * 2 + 1]
        )

    def _query(
        self,
        left: int,
        right: int,
        node: int,
        node_left: int,
        node_right: int,
    ) -> int:
        if right <= node_left or node_right <= left:
            return 0
        if left <= node_left and node_right <= right:
            return self._maximum[node]
        middle = (node_left + node_right) // 2
        return self._lazy[node] + max(
            self._query(left, right, node * 2, node_left, middle),
            self._query(left, right, node * 2 + 1, middle, node_right),
        )


def _validate_table_occupancy(
    cells: tuple[StructuredTableCell, ...],
    *,
    work: RuleUnitProjectionWorkCounter,
) -> None:
    if not cells:
        return
    boundaries = sorted(
        {value for cell in cells for value in (cell.column, cell.column + cell.column_span)}
    )
    work.consume(2 * len(cells))
    boundary_index = {value: index for index, value in enumerate(boundaries)}
    events: list[tuple[int, int, int, int]] = []
    for cell in cells:
        left = boundary_index[cell.column]
        right = boundary_index[cell.column + cell.column_span]
        events.append((cell.row, 1, left, right))
        events.append((cell.row + cell.row_span, 0, left, right))
    work.consume(2 * len(cells))
    events.sort()
    work.consume(_sort_work(len(boundaries)) + _sort_work(len(events)))
    tree = _RangeMaxTree(max(1, len(boundaries) - 1))
    logarithmic_cost = max(1, math.ceil(math.log2(max(2, len(boundaries)))))
    for _, event_kind, left, right in events:
        work.consume(logarithmic_cost)
        if event_kind == 0:
            tree.add(left, right, -1)
        else:
            if tree.maximum(left, right) > 0:
                raise RuleUnitProjectionReviewRequired(
                    "table cell row/column spans overlap canonical occupancy"
                )
            tree.add(left, right, 1)


def _table_group_content_parts(
    cells: tuple[StructuredTableCell, ...],
) -> tuple[tuple[tuple[str, ...], ...], int]:
    """Plan a canonical serialization with each anchored cell represented exactly once."""

    rows: list[tuple[str, ...]] = []
    current_row: int | None = None
    current_texts: list[str] = []
    character_count = 0
    for cell in cells:
        if current_row is not None and cell.row != current_row:
            rows.append(tuple(current_texts))
            character_count += 1
            current_texts = []
        if current_texts:
            character_count += 3
        text = cell.text.strip()
        character_count += len(text)
        current_texts.append(text)
        current_row = cell.row
    if current_texts:
        rows.append(tuple(current_texts))
    elif character_count:
        raise ValueError("table serialization has characters without content rows")
    return tuple(rows), character_count


def _table_group_content(rows: tuple[tuple[str, ...], ...]) -> str:
    return "\n".join(" | ".join(row) for row in rows)


def _candidate_output_characters(candidate: _ProjectionCandidate) -> int:
    values = (
        candidate.content,
        *candidate.heading_path,
        *candidate.definitions,
        candidate.table_title or "",
        *candidate.table_headers,
        candidate.table_context,
        candidate.row_header or "",
    )
    return sum(len(value) for value in values)


def _covered_grid_rows(cells: tuple[StructuredTableCell, ...]) -> tuple[int, ...]:
    intervals = _merge_integer_intervals(
        ((cell.row, cell.row + cell.row_span - 1) for cell in cells),
        merge_adjacent=True,
    )
    return tuple(row for start, end in intervals for row in range(start, end + 1))


def _integer_intervals(values: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    return _merge_integer_intervals(
        ((value, value) for value in values),
        merge_adjacent=True,
    )


def _merge_integer_intervals(
    intervals: Iterable[tuple[int, int]],
    *,
    merge_adjacent: bool = False,
) -> tuple[tuple[int, int], ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()
    merged: list[tuple[int, int]] = []
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        threshold = current_end + 1 if merge_adjacent else current_end
        if start <= threshold:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    merged.append((current_start, current_end))
    return tuple(merged)


def _table_context(table: StructuredTable, header_cells: tuple[StructuredTableCell, ...]) -> str:
    parts: list[str] = []
    if table.title and table.title.strip():
        parts.append(table.title.strip())
    if header_cells:
        parts.append(
            "Headers: "
            + " | ".join(cell.text.strip() for cell in sorted(header_cells, key=lambda c: c.column))
        )
    if table.continuation_of is not None:
        parts.append(f"Continuation of: {table.continuation_of}")
    return "\n".join(parts) or f"Table: {table.table_id}"


def _cell_coordinate(page_number: int, cell: StructuredTableCell) -> RuleCellCoordinate:
    return RuleCellCoordinate(
        page_number=page_number,
        row=cell.row,
        column=cell.column,
        row_span=cell.row_span,
        column_span=cell.column_span,
        bbox=cell.bbox,
    )


def _draft_from_candidate(
    artifact: StructuredKnowledgeDocumentArtifact,
    candidate: _ProjectionCandidate,
    *,
    ordinal: int,
    document_defaults: InsuranceRuleMetadataDraft,
    source_id: str,
) -> InsuranceRuleUnitDraft:
    logical_key_payload = {
        "source_id": source_id,
        "document_id": artifact.document_id,
        "unit_kind": candidate.unit_kind,
        "anchor_parts": candidate.anchor_parts,
    }
    logical_key = f"lrk-{_sha256_json(logical_key_payload)}"
    citation_uri = _citation_uri(
        source_id=source_id,
        document_id=artifact.document_id,
        revision_id=artifact.revision_id,
        page_numbers=candidate.page_numbers,
        anchor_parts=candidate.anchor_parts,
    )
    return InsuranceRuleUnitDraft(
        ordinal=ordinal,
        source_id=source_id,
        document_id=artifact.document_id,
        revision_id=artifact.revision_id,
        original_sha256=artifact.original_sha256,
        structured_build_id=artifact.build_identity.build_id,
        structured_build_identity=artifact.build_identity,
        logical_rule_key=logical_key,
        unit_kind=candidate.unit_kind,
        content=candidate.content,
        citation_uri=citation_uri,
        heading_path=candidate.heading_path,
        definitions=candidate.definitions,
        page_numbers=candidate.page_numbers,
        page_bboxes=candidate.page_bboxes,
        block_ids=candidate.block_ids,
        table_id=candidate.table_id,
        table_continuation_id=candidate.table_continuation_id,
        table_title=candidate.table_title,
        table_headers=candidate.table_headers,
        table_context=candidate.table_context,
        row_header=candidate.row_header,
        row_numbers=candidate.row_numbers,
        header_cell_coordinates=candidate.header_cell_coordinates,
        cell_coordinates=candidate.cell_coordinates,
        inherited_metadata=document_defaults,
    )


def _citation_uri(
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
    page_numbers: tuple[int, ...],
    anchor_parts: tuple[str, ...],
) -> str:
    source_segment = quote(source_id, safe="")
    document_segment = quote(document_id, safe="")
    revision_segment = quote(revision_id, safe="")
    pages = ",".join(str(page) for page in page_numbers)
    anchor = "/".join(quote(part, safe="._~-") for part in anchor_parts)
    fragment = f"pages={pages};anchor={anchor}"
    return (
        f"knowledge://source/{source_segment}/document/{document_segment}/revision/"
        f"{revision_segment}#{fragment}"
    )


def _union_bbox(boxes: Iterable[BoundingBox]) -> BoundingBox:
    materialized = tuple(boxes)
    if not materialized:
        raise ValueError("cannot derive a rule-unit bbox from no source geometry")
    return BoundingBox(
        x0=min(box.x0 for box in materialized),
        y0=min(box.y0 for box in materialized),
        x1=max(box.x1 for box in materialized),
        y1=max(box.y1 for box in materialized),
    )


def _bbox_contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.x0 <= inner.x0 <= inner.x1 <= outer.x1
        and outer.y0 <= inner.y0 <= inner.y1 <= outer.y1
    )


def _sort_work(item_count: int) -> int:
    if item_count < 2:
        return item_count
    return item_count * math.ceil(math.log2(item_count))


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "DEFAULT_RULE_UNIT_PROJECTION_LIMITS",
    "InsuranceRuleUnitDraft",
    "PageBoundingBox",
    "RuleUnitProjectionLimits",
    "RuleUnitProjectionReviewRequired",
    "RuleUnitProjectionWorkCounter",
    "RuleCellCoordinate",
    "project_rule_units",
]
