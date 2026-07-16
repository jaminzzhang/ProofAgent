from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class VaultKvV2ContractService:
    def __init__(self) -> None:
        self.value = "initial-secret"
        self.version = 1
        self.revoked = False
        self.requests: list[tuple[str, Mapping[str, str], Mapping[str, str]]] = []

    def rotate(self, value: str) -> None:
        self.value = value
        self.version += 1

    def get_json(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        query: Mapping[str, str],
    ) -> Mapping[str, Any]:
        self.requests.append((path, dict(headers), dict(query)))
        return {
            "data": {
                "data": {"credential": self.value},
                "metadata": {
                    "version": self.version,
                    "destroyed": self.revoked,
                    "deletion_time": "" if not self.revoked else "2026-07-15T00:00:00Z",
                },
            }
        }
