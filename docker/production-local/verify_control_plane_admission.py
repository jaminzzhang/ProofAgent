"""Run the bounded production-local Control Plane Admission verification."""

from __future__ import annotations

from verify_admission_scorer import control_plane_cli


if __name__ == "__main__":
    raise SystemExit(control_plane_cli())
