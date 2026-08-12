from __future__ import annotations

from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq


def claims_parquet() -> bytes:
    table = pa.table(
        {
            "claim_year": pa.array([2024, 2025], type=pa.int64()),
            "claim_total": pa.array(
                [Decimal("11000.00"), Decimal("12345.67")],
                type=pa.decimal128(12, 2),
            ),
            "active": pa.array([False, True], type=pa.bool_()),
        }
    )
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="NONE")
    return output.getvalue().to_pybytes()
