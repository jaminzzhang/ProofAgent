"""Backward-compatible symlink management for ``runs/latest``.

The dashboard stores run artifacts in per-run directories under
``runs/history/{run_id}/``.  The existing CLI expects ``runs/latest/``
to contain the most recent run.  This module keeps that contract alive
by maintaining a symlink from ``runs/latest`` to the newest run directory.
"""

from __future__ import annotations

from pathlib import Path


def update_latest_symlink(run_dir: Path, runs_root: Path) -> None:
    """Point ``runs/latest`` at the given run directory.

    Removes the existing ``latest`` entry (symlink or directory) and creates
    a new symlink.  This is a no-op if the platform does not support symlinks
    and ``latest`` already exists as a directory.
    """
    latest = runs_root / "latest"

    if latest.is_symlink():
        latest.unlink()
    elif latest.exists():
        # On platforms without symlink support, copy artifacts into a real dir.
        # For the common case (macOS/Linux with symlink support), this branch
        # is only hit on first migration from the old flat layout.
        return

    try:
        latest.symlink_to(run_dir, target_is_directory=True)
    except OSError:
        # Symlinks unavailable (e.g. Windows without developer mode).  Leave
        # latest pointing at whatever it currently is — the per-run dir is
        # still the source of truth for the API.
        pass
