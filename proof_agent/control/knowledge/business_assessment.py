"""Versioned, bounded insurance performance interpretation, derived from source facts.

The orchestrator never owns business names/metric semantics. This profile supports
only explicit source-bound business and metric directions; no global ranking or causes.
"""
import re
from dataclasses import dataclass

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.control.knowledge.performance_analysis import SCOPE_DISCLOSURE, performance_coverage

PROFILE = 'insurance-performance.v2'
BASIS = '比较口径说明：按各指标原文的同比或期初口径分别归纳，不作跨业务排名。'
LIMIT = '判断范围：指标承压不等于整个业务较差；未覆盖的业务不能据此评价。'
ALIASES = {
    '寿险及健康险': ('寿险及健康险', '寿险', '人寿保险'),
    '产险': ('财产保险', '财险', '产险'),
    '银行': ('银行',),
}


@dataclass(frozen=True)
class BusinessFact:
    statement_id: str
    business: str
    statement: str
    citation: str
    directions: frozenset[str]


def _business(text: str) -> str | None:
    found = [name for name, aliases in ALIASES.items() if any(a in text for a in aliases)]
    return found[0] if len(found) == 1 else None


def business_facts(evidence: tuple[EvidenceChunk, ...]) -> tuple[BusinessFact, ...]:
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options
    options = answer_fact_repair_options(evidence)
    result = []
    for i, option in enumerate(options):
        statement = option['statement']
        business = _business(statement)
        if business is None and not any(a in statement for values in ALIASES.values() for a in values):
            # An omitted subject can only inherit an unambiguous heading in the
            # same source chunk. Never use order of retrieved chunks as context.
            contexts = set()
            for e in evidence:
                if e.status is not EvidenceStatus.ACCEPTED or e.citation != option['citation']:
                    continue
                needle = statement.rstrip('。.')
                occurrences = list(re.finditer(re.escape(needle), e.content))
                for match in occurrences:
                    prefix = e.content[:match.start()]
                    headings = re.findall(r'^#{1,6}\s+([^\n]+)', prefix, flags=re.M)
                    paragraph = re.split(r"\n\s*\n", prefix)[-1]
                    paragraph_business = _business(paragraph)
                    heading_business = _business(headings[-1]) if headings else None
                    paragraph_mentions = any(a in paragraph for values in ALIASES.values() for a in values)
                    if paragraph_mentions:
                        contexts.add(paragraph_business if paragraph_business and (not heading_business or heading_business == paragraph_business) else None)
                    else:
                        contexts.add(heading_business)
            if len(contexts) == 1:
                business = next(iter(contexts))
        directions = performance_coverage(statement) & {'strengths', 'pressures'}
        # Coverage alone does not qualify arbitrary metrics. Retain the exact
        # source sentence including conditions and comparison baselines.
        if business and directions:
            result.append(BusinessFact(f's{i}', business, statement, option['citation'], directions))
    return tuple(result)


def assessment_gaps(evidence: tuple[EvidenceChunk, ...], selected_ids: tuple[str, ...] | None = None) -> tuple[str, ...]:
    facts = business_facts(evidence)
    if not facts:
        return ('business_identity',)
    chosen = facts if selected_ids is None else tuple(f for f in facts if f.statement_id in selected_ids)
    gaps = []
    for business in dict.fromkeys(f.business for f in facts):
        expected = set().union(*(f.directions for f in facts if f.business == business))
        available = set().union(*(f.directions for f in chosen if f.business == business))
        for direction in sorted(expected - available):
            gaps.append(f'{business}:{direction}')
    return tuple(gaps)


def render_business_answer(evidence: tuple[EvidenceChunk, ...], selected_ids: tuple[str, ...]) -> str:
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options
    options = answer_fact_repair_options(evidence)
    ids = {f's{i}': o for i, o in enumerate(options)}
    if assessment_gaps(evidence, selected_ids):
        raise ValueError('business_coverage_incomplete')
    facts = tuple(f for f in business_facts(evidence) if f.statement_id in selected_ids)
    strengths = list(dict.fromkeys(f.business for f in facts if 'strengths' in f.directions))
    pressures = list(dict.fromkeys(f.business for f in facts if 'pressures' in f.directions))
    lines = [SCOPE_DISCLOSURE, BASIS,
        '亮点与表现较好的方面：' + ('、'.join(strengths) + '存在增长或成本改善指标。' if strengths else '当前材料未形成可验证的改善判断。'),
        '存在压力的方面：' + ('、'.join(pressures) + '存在承压指标。' if pressures else '当前材料未形成可验证的承压判断。'), LIMIT]
    for business in dict.fromkeys(f.business for f in facts):
        group = tuple(f for f in facts if f.business == business)
        directions = set().union(*(f.directions for f in group))
        label = '增长或成本改善与压力并存' if len(directions) == 2 else ('存在增长或成本改善指标' if 'strengths' in directions else '存在承压指标')
        lines.extend(['', f'{business}：{label}。'])
        lines.extend(f.statement for f in group)
    # Retain selected overall facts, period and non-directional facts without
    # assigning omitted subjects to a fabricated business.
    extra = [ids[i]['statement'] for i in selected_ids if i not in {f.statement_id for f in facts}]
    if extra:
        lines.extend(['', '其他已选事实', *extra])
    return '\n'.join(lines)


def verified_business_body(message: str, evidence: tuple[EvidenceChunk, ...]) -> str | None:
    """Only an exactly reproducible source-bound rendering grants derived prose support."""
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options
    options = answer_fact_repair_options(evidence)
    lines = message.splitlines()
    ids = tuple(f's{i}' for i, o in enumerate(options) if o['statement'] in lines)
    if not 1 <= len(ids) <= 16:
        return None
    # Rendering is canonical by catalogue order, not model-selected order.
    try:
        expected = render_business_answer(evidence, ids)
    except ValueError:
        return None
    if message != expected:
        return None
    return '\n'.join(options[int(i[1:])]['statement'] for i in ids)
