"""User-clause requirement contract; admission belongs to the Control Plane."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AnswerRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    requirement_id: str
    source_text: str = Field(min_length=1, max_length=8192)
    kind: Literal['highlights', 'strengths', 'pressures', 'question']
