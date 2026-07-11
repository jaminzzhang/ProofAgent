"""Backward-compatible symlink management for ``runs/latest``.

The dashboard stores run artifacts in per-run directories under
``runs/history/{run_id}/``.  The existing CLI expects ``runs/latest/``
to contain the most recent run.  This module keeps that contract alive
by maintaining a symlink from ``runs/latest`` to the newest run directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def update_latest_symlink(run_dir: Path, runs_root: Path) -> None:
    """Point ``runs/latest`` at the given run directory.

    Publishes a sibling temporary symlink atomically. This is a no-op if the
    platform does not support symlinks or ``latest`` is a real directory.
    """
    latest = runs_root / "latest"

    if latest.exists() and not latest.is_symlink():
        # On platforms without symlink support, copy artifacts into a real dir.
        # For the common case (macOS/Linux with symlink support), this branch
        # is only hit on first migration from the old flat layout.
        return

    target = Path(os.path.relpath(run_dir.resolve(), latest.parent.resolve()))
    temporary = latest.with_name(f".{latest.name}.{uuid4().hex}.tmp")
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, latest)
    except OSError:
        # Symlinks unavailable (e.g. Windows without developer mode).  Leave
        # latest pointing at whatever it currently is — the per-run dir is
        # still the source of truth for the API.
        pass
    finally:
        if temporary.is_symlink():
            temporary.unlink()
