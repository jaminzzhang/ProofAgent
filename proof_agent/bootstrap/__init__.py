"""Configuration loading, validation, and dependency composition."""

from proof_agent.bootstrap.loader import load_agent_manifest

__all__ = ["HarnessInvocation", "compose_harness_invocation", "load_agent_manifest"]


def __getattr__(name: str) -> object:
    if name in {"HarnessInvocation", "compose_harness_invocation"}:
        from proof_agent.bootstrap.composition import (
            HarnessInvocation,
            compose_harness_invocation,
        )

        return {
            "HarnessInvocation": HarnessInvocation,
            "compose_harness_invocation": compose_harness_invocation,
        }[name]
    raise AttributeError(name)
