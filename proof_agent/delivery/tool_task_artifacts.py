"""Materialize admitted task reports into the existing artifact transaction."""
from html import escape

from proof_agent.contracts import ReceiptOutcome, WorkflowTemplateExecutionResult
from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.control.artifacts.finalization import ArtifactMemberPayload
from proof_agent.control.workflow.controlled_react.artifact_binding import canonical_json_bytes


def tool_task_report_members(result: WorkflowTemplateExecutionResult | None, *, run_id: str) -> tuple[ArtifactMemberPayload, ...]:
    if result is None or result.tool_task_report is None:
        return ()
    report = result.tool_task_report
    payload = canonical_json_bytes(report.model_dump(mode='json'))
    if (result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS or result.run_id != run_id
        or report.run_id != run_id or payload.decode('utf-8') != result.final_output
        or len(payload) > 1024 * 1024):
        raise ValueError('task report does not match the admitted Run result')
    content = ('<!doctype html><html lang="en"><meta charset="utf-8">'
               '<title>Verified task report</title><body><h1>Verified task report</h1><pre>'
               + escape(payload.decode('utf-8')) + '</pre></body></html>').encode('utf-8')
    return (ArtifactMemberPayload(member_id='tool_task_report', kind=ArtifactKind.HTML_REPORT,
        content_type='text/html; charset=utf-8', content=content, display_filename='task-report.html'),)
