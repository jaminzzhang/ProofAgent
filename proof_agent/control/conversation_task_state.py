"""Deterministic user-authored working state, never evidence or authorization."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from proof_agent.contracts.conversation import ConversationRecord, ConversationTaskState, TaskStateItem
from proof_agent.errors import ProofAgentError

_EXPLICIT = re.compile(r"^(Goal|Constraint|目标|约束)\[([\w-]{1,64})\]\s*[:：]\s*(.+)$", re.I)
_REVISION = re.compile(r"^(Revise|Revoke|修订|撤销)\[([\w-]{1,96})\]\s*(?:[:：]\s*(.*))?$", re.I)
_BUDGET = re.compile(r"^(?:Budget\s+(?:is|=)|预算\s*(?:为|是|[:：=]))\s*(\d+(?:\.\d+)?\s*(?:yuan|元|USD|CNY|美元))$", re.I)
_PROHIBITION = re.compile(r'^(Do not |Never |禁止|不得)', re.I)


def _statements(question: str) -> tuple[str, ...]:
    return tuple(statement.strip().rstrip('.。') for statement in re.split(r"(?<!\d)[.!?。！？;；]\s*|\n", question) if statement.strip())


def has_task_statement(question: str) -> bool:
    return any(_EXPLICIT.fullmatch(value) or _REVISION.fullmatch(value) or _BUDGET.fullmatch(value)
        or _PROHIBITION.match(value) for value in _statements(question))


def reduce_task_state(state: ConversationTaskState, question: str, source_id: str) -> ConversationTaskState:
    items = {item.key: item for item in state.items}
    unresolved = list(state.unresolved)
    for statement in _statements(question):
        explicit, revision, budget = _EXPLICIT.fullmatch(statement), _REVISION.fullmatch(statement), _BUDGET.fullmatch(statement)
        if revision:
            action, key, value = revision.groups()
            if key not in items:
                unresolved.append(f"unknown_revision:{key}:{source_id}")
                continue
            if action.lower() in ('revoke', '撤销'):
                del items[key]
                unresolved = [issue for issue in unresolved if f":{key}:" not in issue]
                continue
            if not value:
                unresolved.append(f"empty_revision:{key}:{source_id}")
                continue
            kind = items[key].kind
            unresolved = [issue for issue in unresolved if f":{key}:" not in issue]
        elif explicit:
            label, key, value = explicit.groups()
            kind = 'goal' if label.lower() in ('goal', '目标') else 'constraint'
            if key in items and (items[key].value != value or items[key].kind != kind):
                unresolved.append(f"conflicting_value:{key}:{source_id}")
                continue
            unresolved = [issue for issue in unresolved if f":{key}:" not in issue]
        elif budget:
            key, value, kind = 'budget', budget.group(1), 'constraint'
            if key in items and items[key].value != value:
                unresolved.append(f"conflicting_value:{key}:{source_id}")
                continue
        elif _PROHIBITION.match(statement):
            value, kind = statement + '.', 'constraint'
            key = 'no_submit' if value.lower() == 'do not submit anything.' else 'prohibition_' + sha256(value.encode()).hexdigest()
            if any(item.value == value for item in items.values()):
                continue
        else:
            continue
        if len(value) > 512 or (key not in items and len(items) >= 32):
            unresolved.append(f"state_capacity_exceeded:{source_id}")
            continue
        items[key] = TaskStateItem(key=key, value=value, kind=kind, source_turn_id=source_id)
    return ConversationTaskState(items=tuple(items.values()), unresolved=tuple(dict.fromkeys(unresolved))[:32])


@dataclass(frozen=True)
class TaskStateHistory:
    state: ConversationTaskState
    observed_values: frozenset[str]


def conversation_task_history(conversation: ConversationRecord) -> TaskStateHistory:
    if len(conversation.turns) > 10000 or sum(len(turn.question) for turn in conversation.turns) > 2000000:
        raise ProofAgentError('PA_REACT_001', 'Retained task history exceeds the replay budget.', 'Start a separate conversation with the current explicit constraints.')
    state = ConversationTaskState()
    values: set[str] = set()
    source_ids: set[str] = set()
    for turn in conversation.turns:
        if turn.turn_id in source_ids:
            raise _invalid_state()
        source_ids.add(turn.turn_id)
        expected = reduce_task_state(state, turn.question, turn.turn_id)
        if turn.task_state is not None and turn.task_state != expected:
            raise _invalid_state()
        state = expected
        values.update(item.value for item in state.items)
    return TaskStateHistory(state, frozenset(values))


def conversation_task_state(conversation: ConversationRecord) -> ConversationTaskState:
    return conversation_task_history(conversation).state


def _invalid_state() -> ProofAgentError:
    return ProofAgentError('PA_REACT_001', 'Task state does not match retained user-turn sources.',
        'Start a separate conversation and restate the current constraints; do not reuse an inconsistent snapshot.')


def render_task_state(state: ConversationTaskState) -> str:
    if not state.items and not state.unresolved:
        return ''
    rows = ['User task state (not evidence or authorization):']
    rows.extend(f'{item.kind}[{item.key}]={item.value} (source={item.source_turn_id})' for item in state.items)
    if state.unresolved:
        rows.append('UNRESOLVED task state; ask for clarification: ' + ', '.join(state.unresolved))
    return '\n'.join(rows)
