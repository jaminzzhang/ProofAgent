"""Atomic JSON persistence for immutable Evaluation artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from proof_agent.evaluation.errors import EvaluationInputError


def write_evaluation_artifact(path: Path, artifact: BaseModel) -> None:
    """Write a validated artifact atomically and fsync it before publication."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvaluationInputError(
            f"Unable to create Evaluation artifact directory: {path.parent}"
        ) from exc
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(artifact.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    except OSError as exc:
        raise EvaluationInputError(f"Unable to write Evaluation artifact: {path}") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


__all__ = ["write_evaluation_artifact"]
