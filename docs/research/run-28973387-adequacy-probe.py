"""Offline red-capable completeness probe. No model calls or capture copying."""
import json
from pathlib import Path

from proof_agent.contracts import ReceiptOutcome, ValidationStatus
from proof_agent.control.knowledge.performance_analysis import performance_coverage
from proof_agent.control.workflow.harness_helpers import validate_final_answer_adequacy

root = Path(__file__).resolve().parents[2]
events = [json.loads(line) for line in (root / 'runs/dify-verification/history/run_28973387/trace.jsonl').read_text().splitlines()]
final = next(e['payload'] for e in events if e['event_type'] == 'final_output')
citations = tuple(dict.fromkeys(c for e in events if e['event_type'] == 'workflow_stage_result' for c in e['payload'].get('summary', {}).get('citation_refs', [])))
# Isolate adequacy: the real answer and citation refs already passed evidence/fact gates.
# Evidence is intentionally empty, removing dump-similarity as an unrelated variable.
for label, message in (
    ('actual_answer', final['message']),
    ('one_business_metrics_only', '2026 年第一季度，平安寿险营运利润增长 6.4%。寿险新业务价值率下降 4.8 个百分点。'),
):
    result = validate_final_answer_adequacy(question=final['question'], message=message, citations=citations, evidence=(), outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    print(label, 'coverage=', sorted(performance_coverage(message)), 'adequacy=', result.status.value)
    if label == 'actual_answer':
        actual = result
assert actual.status is ValidationStatus.FAILED, 'BUG: ungrouped metrics pass without answering which businesses perform well or poorly'
