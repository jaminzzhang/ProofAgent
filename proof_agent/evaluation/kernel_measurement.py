"""Fixed local V3 observations; never release evidence or provider cost estimates."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import platform
import sys
from time import perf_counter_ns
from types import FrameType
from typing import Any

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.evaluation.demo.kernel_probes import (
    FACT_A, FACT_B, QUERY_A, QUERY_B, exercise_retrieval,
)
from proof_agent.evaluation.kernel_baseline import baseline_source_fingerprint

VERSION = 'kernel-measurement.v2'
# Fixed questions, required queries and expected admitted facts are hashed together.
SCENARIOS = (
    ('single_retrieval', 'Retrieve Alpha policy reimbursement limit.', (QUERY_A,), (FACT_A,)),
    ('compound_retrieval', 'Retrieve Alpha reimbursement and Beta waiting period, then compare both policies.',
     (QUERY_A, QUERY_B), (FACT_A, FACT_B)),
)


@dataclass(frozen=True)
class ScenarioMeasurement:
    scenario_id: str
    passed: bool
    elapsed_ms: float
    model_calls: int
    tokens: int | None
    cost: float | None


@dataclass(frozen=True)
class MeasurementReport:
    version: str
    source_fingerprint: str
    sample_fingerprint: str
    environment: str
    required_ids: tuple[str, ...]
    samples: tuple[ScenarioMeasurement, ...]
    source_stable: bool
    execution_scope: str = 'synthetic_local_existing_v3'
    production_readiness: str = 'not_evaluated'
    token_scope: str = 'provider_reported_only'
    instrumentation: str = 'synchronous_outermost_model_port_generate'
    quality_scope: str = 'required_retrieval_and_admitted_input_coverage_only'


class ModelCallObserver:
    """Profile existing synchronous ModelProvider calls without replacing execution.

    This fixed fixture runs on the calling thread. All Python generate(request:
    ModelRequest) calls are counted, including exceptions and absent usage. No
    arguments, prompts, outputs or exception payloads are retained. Nested
    wrappers count once; asynchronous providers are outside this version's scope.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.tokens = 0
        self.missing_usage = False
        self.active: set[int] = set()

    def observe(self, frame: FrameType, event: str, arg: Any) -> None:
        if event == 'call' and frame.f_code.co_name == 'generate' and isinstance(
            frame.f_locals.get('request'), ModelRequest
        ):
            parent = frame.f_back
            while parent is not None:
                if id(parent) in self.active:
                    return
                parent = parent.f_back
            self.calls += 1
            self.active.add(id(frame))
        elif event == 'return' and id(frame) in self.active:
            self.active.remove(id(frame))
            usage = arg.token_usage if isinstance(arg, ModelResponse) else None
            if usage is None or usage.input_tokens < 0 or usage.output_tokens < 0:
                self.missing_usage = True
            else:
                total = usage.input_tokens + usage.output_tokens
                if usage.total_tokens is not None and usage.total_tokens != total:
                    self.missing_usage = True
                self.tokens += total


def _sample_fingerprint(root: Path) -> str:
    digest = sha256(json.dumps(SCENARIOS, ensure_ascii=False).encode())
    # Harness fixture, wire fixture construction and quality predicate are inputs.
    paths = [root / 'proof_agent/evaluation/demo/kernel_probes.py']
    paths.extend(sorted((root / 'proof_agent/evaluation/demo/fixtures').rglob('*.yaml')))
    paths.extend(sorted((root / 'proof_agent/evaluation/demo/fixtures').rglob('*.json')))
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(sha256(path.read_bytes()).digest())
    return 'sha256:' + digest.hexdigest()


def run_measurement(*, root: Path) -> MeasurementReport:
    if sys.getprofile() is not None:
        raise RuntimeError('measurement requires an uninstrumented synchronous thread')
    before = baseline_source_fingerprint(root)
    samples = []
    for scenario_id, question, queries, facts in SCENARIOS:
        observer = ModelCallObserver()
        start = perf_counter_ns()
        passed = False
        sys.setprofile(observer.observe)
        try:
            observation = exercise_retrieval(question=question, queries=queries)
            passed = set(queries).issubset(observation.queries) and all(
                observation.contains_admitted_fact(fact) for fact in facts
            )
        except Exception:
            # Fixed error state only; exception strings may contain provider data.
            passed = False
        finally:
            sys.setprofile(None)
        samples.append(ScenarioMeasurement(
            scenario_id, passed, (perf_counter_ns() - start) / 1_000_000,
            observer.calls,
            None if observer.missing_usage or observer.active else observer.tokens,
            None,
        ))
    environment = '|'.join((platform.python_implementation(), platform.python_version(),
                            platform.system(), platform.release(), platform.machine()))
    return MeasurementReport(VERSION, before, _sample_fingerprint(root), environment,
                             tuple(item[0] for item in SCENARIOS), tuple(samples),
                             baseline_source_fingerprint(root) == before)


def _complete(report: MeasurementReport) -> bool:
    ids = tuple(sample.scenario_id for sample in report.samples)
    return bool(report.required_ids) and report.source_stable and (
        len(ids) == len(set(ids)) == len(report.required_ids)
        and set(ids) == set(report.required_ids)
        and len(set(report.required_ids)) == len(report.required_ids)
        and all(sample.passed is True and isfinite(sample.elapsed_ms) and sample.elapsed_ms >= 0
                and type(sample.model_calls) is int and sample.model_calls >= 0
                and (sample.tokens is None or type(sample.tokens) is int and sample.tokens >= 0)
                and (sample.cost is None or isfinite(sample.cost) and sample.cost >= 0)
                for sample in report.samples)
    )


def compare_measurements(baseline: MeasurementReport, current: MeasurementReport) -> dict[str, Any]:
    matched = _complete(baseline) and _complete(current) and all(
        getattr(baseline, key) == getattr(current, key)
        for key in ('version', 'sample_fingerprint', 'environment', 'required_ids',
                    'execution_scope', 'token_scope', 'instrumentation', 'quality_scope')
    )
    result: dict[str, Any] = {
        'matched': matched, 'status': 'matched_observation' if matched else 'not_comparable',
        'baseline_source': baseline.source_fingerprint, 'current_source': current.source_fingerprint,
        'production_readiness': 'not_evaluated',
    }
    for field, output in (('elapsed_ms', 'elapsed_ms_delta'), ('model_calls', 'model_calls_delta'),
                          ('tokens', 'tokens_delta'), ('cost', 'cost_delta')):
        old = [getattr(item, field) for item in baseline.samples]
        new = [getattr(item, field) for item in current.samples]
        result[output] = sum(new) - sum(old) if matched and None not in old + new else None
    return result


def write_measurement(report: MeasurementReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
