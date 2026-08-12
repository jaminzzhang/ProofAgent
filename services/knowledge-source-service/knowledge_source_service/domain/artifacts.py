"""Exact immutable artifact identities owned by the Knowledge service."""

from __future__ import annotations

from dataclasses import dataclass
import re


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ExactArtifactReference:
    """Storage-neutral exact object version plus independently verified integrity."""

    object_key: str
    version_id: str
    sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        if (
            not self.object_key
            or self.object_key.startswith("/")
            or ".." in self.object_key
            or "//" in self.object_key
            or any(ord(character) < 32 for character in self.object_key)
        ):
            raise ValueError("artifact object key is invalid")
        if not self.version_id:
            raise ValueError("artifact version identity is required")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("artifact sha256 is invalid")
        if self.size_bytes < 1:
            raise ValueError("artifact length must be positive")
        if not self.media_type or len(self.media_type) > 255:
            raise ValueError("artifact media type is invalid")
