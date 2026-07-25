"""Shared shell-free command boundary for external deployment controllers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
import subprocess
from typing import Protocol


_MAX_COMMAND_OUTPUT_BYTES = 1_048_576


class DeploymentToolError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class CommandResult:
    stdout: str


class DeploymentCommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    """Run an argument vector without a shell and never echo captured output."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if not argv or any(not item or "\x00" in item for item in argv):
            raise DeploymentToolError("deployment_command_invalid")
        if not 1 <= timeout_seconds <= 1800:
            raise DeploymentToolError("deployment_command_timeout_invalid")
        if env is not None and any(
            not key
            or "\x00" in key
            or "=" in key
            or "\x00" in value
            for key, value in env.items()
        ):
            raise DeploymentToolError("deployment_command_environment_invalid")
        try:
            completed = subprocess.run(
                list(argv),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_seconds,
                shell=False,
                env=None if env is None else {**os.environ, **env},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeploymentToolError("deployment_command_unavailable") from exc
        if (
            len(completed.stdout) > _MAX_COMMAND_OUTPUT_BYTES
            or len(completed.stderr) > _MAX_COMMAND_OUTPUT_BYTES
        ):
            raise DeploymentToolError("deployment_command_output_too_large")
        if completed.returncode != 0:
            raise DeploymentToolError("deployment_command_failed")
        try:
            stdout = completed.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DeploymentToolError("deployment_command_output_invalid") from exc
        return CommandResult(stdout=stdout)


__all__ = [
    "CommandResult",
    "DeploymentCommandRunner",
    "DeploymentToolError",
    "SubprocessCommandRunner",
]
