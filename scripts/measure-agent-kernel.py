#!/usr/bin/env python3
"""Measure fixed synchronous V3 retrieval coverage; never infer release readiness."""
from __future__ import annotations

import argparse
import json
from math import ceil
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proof_agent.evaluation.kernel_measurement import (  # noqa: E402
    compare_measurements, run_measurement, write_measurement,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=3, choices=range(1, 31))
    args = parser.parse_args()
    reports = []
    try:
        for index in range(args.repetitions):
            report = run_measurement(root=ROOT)
            write_measurement(report, args.output_dir / f'measurement-{index + 1:02d}.json')
            reports.append(report)
        matched = all(compare_measurements(reports[0], item)['matched']
            and item.source_fingerprint == reports[0].source_fingerprint for item in reports)
        scenarios = []
        for scenario_id in reports[0].required_ids:
            samples = [sample for report in reports for sample in report.samples if sample.scenario_id == scenario_id]
            elapsed = sorted(sample.elapsed_ms for sample in samples)
            scenarios.append({'scenario_id': scenario_id, 'repetitions': len(samples),
                'p50_elapsed_ms': statistics.median(elapsed) if matched else None,
                'p95_elapsed_ms': elapsed[ceil(.95 * len(elapsed)) - 1] if matched else None,
                'model_calls': [sample.model_calls for sample in samples],
                'tokens': [sample.tokens for sample in samples], 'cost': None})
        summary = {'schema_version': 'kernel-measurement-series.v1',
            'status': 'measured' if matched else 'needs_review',
            'source_fingerprint': reports[0].source_fingerprint,
            'sample_fingerprint': reports[0].sample_fingerprint,
            'environment': reports[0].environment, 'quality_scope': reports[0].quality_scope,
            'execution_scope': reports[0].execution_scope, 'production_readiness': 'not_evaluated',
            'performance_improvement': 'not_established',
            'scenarios': scenarios}
        (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    except Exception:
        print('kernel measurement: infrastructure error', file=sys.stderr)
        return 2
    print('kernel measurement: ' + summary['status'])
    print('scope: synthetic_local; answer correctness and production readiness: not evaluated')
    return 0 if matched else 1


if __name__ == '__main__':
    raise SystemExit(main())
