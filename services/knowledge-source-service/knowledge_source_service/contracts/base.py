"""Shared strict primitives for public Knowledge Source Service contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StrictContract(BaseModel):
    """Base for service contracts that reject undeclared caller input."""

    model_config = ConfigDict(extra="forbid")
