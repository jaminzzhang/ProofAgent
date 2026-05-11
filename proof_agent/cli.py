"""Backward-compatible CLI module.

The implementation lives in :mod:`proof_agent.delivery.cli` so the directory
layout reflects the architecture, while existing console scripts and imports
continue to work.
"""

from proof_agent.delivery.cli import app, main

__all__ = ["app", "main"]
