from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook


def claims_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Claims"
    sheet.append(("claim_year", "claim_total", "active"))
    sheet.append((2024, 11000.00, False))
    sheet.append((2025, 12345.67, True))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
