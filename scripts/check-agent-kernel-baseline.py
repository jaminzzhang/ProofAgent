#!/usr/bin/env python3
"""Run fixed offline probes; exit 0 only when every measured requirement passes."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proof_agent.evaluation.kernel_baseline import run_baseline_check  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        status = run_baseline_check(artifact_dir=args.output_dir, root=ROOT)
    except Exception:
        # Do not expose arbitrary exception payloads, paths or model data on the CLI.
        print("kernel baseline: measurement infrastructure error", file=sys.stderr)
        return 2
    print("kernel baseline: " + ("passed_with_diagnostics" if status == 0 else "needs_review"))
    print("scope: synthetic_local; production_readiness: not_evaluated")
    print(f"report: {args.output_dir.resolve() / 'kernel_baseline.md'}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
