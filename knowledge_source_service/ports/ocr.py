"""Provider-neutral bounded OCR boundary for scanned document intake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OcrRegion:
    page_number: int
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    text: str

    def __post_init__(self) -> None:
        if not 1 <= self.page_number <= 1_000:
            raise ValueError("OCR region page is invalid")
        if (
            min(self.x_min, self.y_min) < 0
            or self.x_max <= self.x_min
            or self.y_max <= self.y_min
        ):
            raise ValueError("OCR region bounding box is invalid")
        if not self.text.strip():
            raise ValueError("OCR region text must not be blank")


@dataclass(frozen=True)
class OcrPage:
    page_number: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not 1 <= self.page_number <= 1_000:
            raise ValueError("OCR page number is invalid")
        if min(self.width, self.height) < 1:
            raise ValueError("OCR page dimensions are invalid")
        if self.width * self.height > 100_000_000:
            raise ValueError("OCR page exceeds the admitted pixel bound")


@dataclass(frozen=True)
class OcrDocument:
    model_revision: str
    regions: tuple[OcrRegion, ...]
    pages: tuple[OcrPage, ...] = ()

    def __post_init__(self) -> None:
        if not self.model_revision.strip():
            raise ValueError("OCR model revision must not be blank")
        if not self.regions or len(self.regions) > 100_000:
            raise ValueError("OCR region count is outside the admitted bound")
        locators = {
            (
                region.page_number,
                region.x_min,
                region.y_min,
                region.x_max,
                region.y_max,
            )
            for region in self.regions
        }
        if len(locators) != len(self.regions):
            raise ValueError("OCR region locators must be unique")
        if self.pages:
            if tuple(page.page_number for page in self.pages) != tuple(
                range(1, len(self.pages) + 1)
            ):
                raise ValueError("OCR pages must be contiguous and ordered")
            if any(region.page_number > len(self.pages) for region in self.regions):
                raise ValueError("OCR region references an unknown page")


class DocumentOcrExtractor(Protocol):
    def extract(self, *, media_type: str, content: bytes) -> OcrDocument: ...
