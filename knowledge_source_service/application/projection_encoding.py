"""Pinned provider-neutral encoding seam for Dense and Sparse projections."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
import re
from typing import Protocol


@dataclass(frozen=True)
class EncodedProjectionText:
    dense_vector: tuple[float, ...]
    sparse_vector: dict[str, float]


class ProjectionTextEncoder(Protocol):
    dense_revision: str
    sparse_revision: str
    dense_dimension: int

    def encode(self, text: str) -> EncodedProjectionText: ...


class DeterministicHashProjectionEncoder:
    """Deterministic bounded baseline encoder with explicit immutable revisions."""

    dense_revision = "hashing-dense-v1"
    sparse_revision = "hashing-sparse-v1"

    def __init__(self, *, dense_dimension: int) -> None:
        if dense_dimension < 4 or dense_dimension > 4096:
            raise ValueError("dense_dimension must be between 4 and 4096")
        self.dense_dimension = dense_dimension

    def encode(self, text: str) -> EncodedProjectionText:
        terms = _terms(text)
        dense = [0.0] * self.dense_dimension
        sparse: dict[str, float] = {}
        for term in terms:
            digest = sha256(term.encode()).digest()
            dense_index = int.from_bytes(digest[:4]) % self.dense_dimension
            sign = 1.0 if digest[4] & 1 == 0 else -1.0
            weight = 1.0 / sqrt(max(1, len(term)))
            dense[dense_index] += sign * weight
            sparse_feature = f"f{int.from_bytes(digest[5:9]) % 4096:04d}"
            sparse[sparse_feature] = sparse.get(sparse_feature, 0.0) + weight
        norm = sqrt(sum(value * value for value in dense))
        if norm == 0:
            raise ValueError("projection text produced no vector features")
        return EncodedProjectionText(
            dense_vector=tuple(value / norm for value in dense),
            sparse_vector=dict(sorted(sparse.items())),
        )


def _terms(value: str) -> tuple[str, ...]:
    normalized = value.casefold()
    terms = set(re.findall(r"[a-z0-9_]+", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        terms.update(run)
        terms.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    if not terms and normalized.strip():
        terms.add(normalized.strip())
    if not terms:
        raise ValueError("projection text must not be blank")
    return tuple(sorted(terms))
