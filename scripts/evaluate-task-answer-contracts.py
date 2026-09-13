"""Fixed synthetic development evaluation; not a held-out or real-model benchmark.

Run: PYTHONPATH=. .venv/bin/python scripts/evaluate-task-answer-contracts.py
Prints only case identifiers and validation outcomes. No provider/network access.
"""
import json

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ModelResponse, ReceiptOutcome
from proof_agent.control.knowledge.business_assessment import render_business_answer
from proof_agent.control.validators.answer_facts import answer_fact_repair_options
from proof_agent.control.workflow.harness_helpers import validate_model_output

question = '甲公司业绩有哪些亮点，哪些业务比较好，哪些业务比较差？'
source = '2026 年第一季度，甲公司寿险业务营运利润 100 亿元，同比增长 6%。\n甲公司寿险新业务价值率 23%，同比下降 4 个百分点。'
evidence = (EvidenceChunk(source='synthetic://evaluation/report', citation='synthetic://evaluation/report#L1', content=source, status=EvidenceStatus.ACCEPTED),)
options = answer_fact_repair_options(evidence)
grouped = render_business_answer(evidence, tuple(f's{i}' for i in range(len(options))))
cases = [
    ('factual_lookup', '甲公司寿险营运利润是多少？', source.splitlines()[0], True, True),
    ('flat_metrics', question, source, True, False),
    ('headers_only', question, '表现较好\n' + source + '\n业务承压', True, False),
    ('grounded_mixed_analysis', question, grouped, True, True),
    ('altered_number', question, grouped.replace('100 亿元', '999 亿元'), False, False),
    ('unsupported_ranking', question, grouped.replace('增长或成本改善与压力并存', '整体表现最差'), False, False),
    ('wrong_period', question, grouped.replace('2026', '2024'), False, False),
    ('negative_omitted', question, source.splitlines()[0], True, False),
]
results = []
for case_id, q, message, facts_expected, completion_expected in cases:
    validation = validate_model_output(question=q, evidence=evidence, outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        response=ModelResponse(content=json.dumps({'message': message, 'citations': [evidence[0].citation]}), provider_name='offline', model_name='evaluation', finish_reason='stop'))
    observed = {r.validator_name: r.status.value == 'passed' for r in validation}
    matched = observed['answer_facts'] == facts_expected and observed['final_answer_adequacy'] == completion_expected
    results.append({'case_id': case_id, 'facts_passed': observed['answer_facts'], 'completion_passed': observed['final_answer_adequacy'], 'expected_behavior_matched': matched})
print(json.dumps({'evaluation_kind': 'fixed_synthetic_development_cases', 'model_calls': 0, 'cases': results,
                  'matched': sum(r['expected_behavior_matched'] for r in results), 'total': len(results)}, indent=2))
assert all(r['expected_behavior_matched'] for r in results)
