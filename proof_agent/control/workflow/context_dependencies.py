"""Bounded request/field dependency rules; unknown dependencies remain blocking.

This profile corrects a known purchase-consultation misclassification. It is not
a general semantic classifier and never establishes tool or Task authority.
"""

import re


PURCHASE_SCOPE = "本轮按购前产品与适合性咨询处理；不要求已持有该产品的保单资料，个人适合性依据已提供信息与检索证据分析，确有缺口时再询问。"


def irrelevant_purchase_policy_field(question: str, field: str) -> bool:
    """Recognize only an existing-product-policy field in a purchase question.

    Full-field matching prevents a compound permission/identity requirement from
    being discarded just because it also mentions a policy. Any policy-specific
    operation in the question keeps its dependencies, including mixed requests.
    Callers must additionally retain frozen Task and tool-input requirements.
    """
    if not re.search(r"保险|寿险|重疾险|医疗险|意外险|年金险", question):
        return False
    if not re.search(r"适合.{0,8}(?:买|购买|投保|我)|(?:要不要|该不该|能不能|是否应该|想|准备|打算)(?:买|购买|投保)", question):
        return False
    if re.search(
        r"保单|合同|理赔|退保|续保|领取|已买|买过|买了|买的|已购|已投保|投保了|投保过|"
        r"已持有|已购买|加保|减保|保全|受益人|报案|出险|我的.{0,6}(?:赔|现金价值)",
        question,
    ):
        return False
    return re.fullmatch(
        r"(?:用户)?(?:是否(?:已经|已)?(?:投保|购买)(?:该|此|本)?产品(?:及|和)?)?"
        r"(?:具体)?保单(?:信息|资料|编号|号|详情)"
        r"(?:[（(](?:如有追问需要|如有|若有)[）)])?[？?]?",
        field.strip(),
    ) is not None
