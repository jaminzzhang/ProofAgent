from dataclasses import replace
from pathlib import Path

from proof_agent.evaluation.kernel_measurement import (
    ScenarioMeasurement, MeasurementReport, compare_measurements, run_measurement,
)


def report(**changes):
    base = MeasurementReport('kernel-measurement.v1', 'sha256:a', 'sha256:s', 'env',
        ('one',), (ScenarioMeasurement('one', True, 10.0, 3, None, None),), True)
    return replace(base, **changes)


def test_missing_usage_and_cost_cannot_improve():
    result = compare_measurements(report(), report(source_fingerprint='sha256:b'))
    assert result['matched'] is True
    assert result['tokens_delta'] is None
    assert result['cost_delta'] is None


def test_failed_missing_duplicate_changed_samples_cannot_improve():
    for current in (
        report(samples=()), report(samples=report().samples * 2),
        report(samples=(replace(report().samples[0], passed=False, elapsed_ms=0.1),)),
        report(sample_fingerprint='sha256:changed'), report(environment='other'),
        report(source_stable=False), report(required_ids=()),
    ):
        result = compare_measurements(report(), current)
        assert result['matched'] is False
        assert result['elapsed_ms_delta'] is None


def test_actual_v3_scenario_records_calls_and_missing_usage():
    result = run_measurement(root=Path(__file__).resolve().parents[1])
    assert result.source_stable
    assert len(result.samples) == len(result.required_ids) == 2
    assert all(sample.passed and sample.elapsed_ms > 0 for sample in result.samples)
    assert all(sample.model_calls >= 4 for sample in result.samples)
    assert all(sample.tokens is None and sample.cost is None for sample in result.samples)


def test_nested_provider_wrapper_counts_one_logical_model_call():
    import sys
    from proof_agent.contracts import ModelRequest, ModelResponse, TokenUsage
    from proof_agent.evaluation.kernel_measurement import ModelCallObserver
    class Provider:
        def generate(self, request):
            return ModelResponse(content='ok', provider_name='deterministic', model_name='demo',
                token_usage=TokenUsage(input_tokens=2, output_tokens=1, total_tokens=3))
    class Wrapper:
        def generate(self, request):
            return Provider().generate(request)
    observer = ModelCallObserver()
    request = ModelRequest(provider='deterministic', model='demo', messages=[])
    sys.setprofile(observer.observe)
    try:
        Wrapper().generate(request)
    finally:
        sys.setprofile(None)
    assert observer.calls == 1
    assert observer.tokens == 3
