from __future__ import annotations

from io import BytesIO

from PIL import Image

from knowledge_source_service.ports.ocr import OcrDocument, OcrPage, OcrRegion


class ReviewedOcrExtractor:
    def extract(self, *, media_type: str, content: bytes) -> OcrDocument:
        assert media_type == "image/png"
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        return OcrDocument(
            model_revision="ocr-private-v3",
            regions=(
                OcrRegion(
                    page_number=1,
                    x_min=10,
                    y_min=12,
                    x_max=190,
                    y_max=42,
                    text="Flight delay benefit is 300 CNY after four hours.",
                ),
            ),
        )


class ReviewedPdfOcrExtractor:
    def extract(self, *, media_type: str, content: bytes) -> OcrDocument:
        assert media_type == "application/pdf"
        assert content.startswith(b"%PDF-")
        return OcrDocument(
            model_revision="ocr-private-v3",
            pages=(OcrPage(page_number=1, width=612, height=792),),
            regions=(
                OcrRegion(
                    page_number=1,
                    x_min=72,
                    y_min=60,
                    x_max=420,
                    y_max=100,
                    text="Scanned flight delay benefit is 500 CNY.",
                ),
            ),
        )


def blank_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (200, 100), color="white").save(output, format="PNG")
    return output.getvalue()
