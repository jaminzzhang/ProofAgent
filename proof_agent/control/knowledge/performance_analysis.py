"""Bounded two-sided performance contract; not a general semantic judge.

Only explicit, requested performance comparisons activate this local profile.
Known metric directions support coverage, never cross-business rankings or causality.
"""

import re
from decimal import Decimal


SCOPE_DISCLOSURE = "资料范围说明：以下仅整理本次检索材料，未确认最新性或完整覆盖。"


def is_performance_comparison(question: str) -> bool:
    return bool(
        re.search(r"业绩|经营表现|业务表现", question)
        and re.search(r"亮点|较好|比较好|优势|增长", question)
        and re.search(r"较差|比较差|弱项|不足|压力|劣势|下滑", question)
    )


def performance_coverage(text: str) -> frozenset[str]:
    """Match explicit figures and directions within a sentence, never across rows."""
    found: set[str] = set()
    for sentence in re.split(r"[。；;\n]", text):
        if not re.search(r"\d", sentence) or re.search(
            r"预计|预测|假设|目标|不代表|并非|不意味着|如果|若", sentence
        ):
            continue
        if re.search(r"20\d{2}\s*年.*(?:季度|半年|年报|年度|期间)", sentence):
            found.add("period")
        # Table headers can appear after the period label.
        if "期间" in sentence and len(re.findall(r"20\d{2}\s*年", sentence)) >= 2:
            found.add("period")
        metric = r"营运利润|净利润|营业收入|保费收入|新业务价值(?!率)"
        change = re.search(
            r"(?:变动|同比)[（(]%[）)]：\s*([+-]?\d+(?:\.\d+)?)\s*(?:，|$)", sentence
        )
        if change:
            delta = Decimal(change.group(1))
            growth_metric = bool(re.search(metric, sentence))
            rate_metric = bool(re.search(r"新业务价值率|净息差|拨备覆盖率", sentence))
            if (growth_metric and delta > 0) or ("综合成本率" in sentence and delta < 0):
                found.add("strengths")
            if ((growth_metric or rate_metric) and delta < 0) or (
                "综合成本率" in sentence and delta > 0
            ):
                found.add("pressures")
        if re.search(rf"(?:{metric}).*(?:增长|增加|上升)\s*[+]?\d", sentence) or re.search(
            r"综合成本率.*(?:下降|优化)\s*\d", sentence
        ):
            found.add("strengths")
        if (
            re.search(
                r"(?:价值率|净息差|拨备覆盖率|营运利润|净利润|营业收入|保费收入).*下降\s*\d",
                sentence,
            )
            or re.search(r"(?:净亏损|亏损扩大|减值损失增加)\s*\d", sentence)
            or re.search(r"综合成本率.*上升\s*\d", sentence)
        ):
            found.add("pressures")
    return frozenset(found)


def missing_performance_coverage(question: str, text: str) -> tuple[str, ...]:
    if not is_performance_comparison(question):
        return ()
    found = performance_coverage(text)
    return tuple(part for part in ("period", "strengths", "pressures") if part not in found)
