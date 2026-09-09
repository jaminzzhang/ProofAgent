# Unified Workflow Prompt verification

Date: 2026-09-09. Decision: ADR-0251.

[KNOWN | HIGH] LOCAL_VERIFIED for the requested Workflow editor change. User authorized
merging the three fields into one Prompt with templates. No production configuration,
Agent publication, Git commit or unrelated working-tree edits were performed.

## Scope and acceptance

- One free-form Prompt for editable stages; non-editable stages show an explanation.
- One structural template appends Business Context, Task Instructions and Output Preferences
  headings and fill-in hints. Business and stage-specific templates were removed after clarification.
- Legacy fields preserve text and ordering; saved merged text is not duplicated on reload.
- Preview/save/YAML share the editor value; old in-flight previews cannot overwrite a
  newer edit or stage selection.
- YAML parsing handles real backend multiline serialization, quotes, Unicode, backslashes
  and strings resembling booleans, numbers or null. Added the `yaml` parser dependency.
- The compatibility carrier accepts merged text above 2,000 characters, while the
  aggregate 12,000-character budget and existing governance validators remain enforced.

## RED and GREEN

RED observed: no Prompt field; former 2,000-character field limit rejected merged text;
newlines returned as literal backslash-n after reload; stale preview appeared after edit;
boolean/number/null-like strings changed type in the YAML projection. All repaired and
covered by the final tests. Sandbox and package-cache failures were environment issues,
not RED evidence.

| Command / evidence | Result |
| --- | --- |
| `npm run test -w proof-agent-dashboard -- src/components/__tests__/agent/WorkflowModuleEditor.test.tsx src/utils/agentYaml.test.ts` | 36 passed |
| `npm run test -w proof-agent-dashboard` | All 40 test files passed; Vitest results cache confirmed no failed files |
| `npm run build:dashboard` | TypeScript and Vite build passed; main chunk size warning at 519.78 kB, 135.35 kB gzip |
| `.venv/bin/python -m pytest tests/test_agent_configuration_api.py tests/test_agent_configuration_workspace.py tests/test_config_loader.py tests/test_workflow_stage_context.py tests/test_workflow_templates.py -q` | 223 passed, 2 skipped |
| `.venv/bin/ruff check proof_agent/control/workflow/stage_validation.py tests/test_config_loader.py` | Passed |
| `git diff --check` | Passed |
| ego-browser, actual component with synthetic Plan/Response fixture | Typed multiline Chinese, inserted insurance template, simulated save/reload: exact text preserved; desktop 1280 px and narrow 390 px: no horizontal overflow; screenshots inspected |

Browser verification used a temporary fixture rendering the actual component and
callbacks, not a live Agent or production API. Backend API/workspace tests exercised
the existing save/validation path separately. No live model/provider execution or release
verification was performed. Runtime prompt projection retains its existing length bounds.

## Review

Self-review only. Verified explicit legacy adapter, retained backend aggregate/content
checks, no Prompt controls on deterministic stages, no implicit template replacement,
reload fidelity, and revision-bound preview results. The unrelated working-tree changes
present at task start were preserved. Temporary browser fixture/server were removed.

## Tested file fingerprints

- `dashboard/src/components/agent/WorkflowModuleEditor.tsx`: `334f4174c6850ea9b36bb4971282d067a8fe671c9c0d756077fa3a4095b07ede`
- `dashboard/src/components/agent/workflowPrompt.ts`: `19f71ed4131486d62bfe11906efb432ff5d347570588b9250b2551791ce7bbaa`
- `dashboard/src/utils/agentYaml.ts`: `8501cdf6edecee37bbaabc6401636900dcedaf299422dc9b9bd94a43fe69feff`
- `dashboard/src/components/__tests__/agent/WorkflowModuleEditor.test.tsx`: `d9b0c47421d2db0c4c3e3d0d7a1c91d24ff1152e177071ec847fb540f1dacf40`
- `dashboard/src/pages/__tests__/AgentDetailPage.test.tsx`: `c0760abdbeeb1b5d7758e5aa824b8ad03c0e980a13a7ffc64c022c0248aba97b`
- `dashboard/src/utils/agentYaml.test.ts`: `d98a769a2bc3436cf6893154d1e8b57a53ac8c214894a4d886a47dc5497eed0f`
- `dashboard/package.json`: `f5a63652d8c5b36edba3a0b1d6f65e2a57336c1d1f8b2716026dbee37bca8fb2`
- `package-lock.json`: `ff65596ba6054567359dd83386189e3fd6011e7420812fee83e8916518bf6a71`
- `proof_agent/control/workflow/stage_validation.py`: `89cb09c53cb9a49292dfaca2ae154f95c54972b7013e8ab473d916687c806d5b`
- `tests/test_config_loader.py`: `841d50b4e4aebeaca8e350f16d69f84c1ef8fba6b67b3567e676c11a9554d990`

## User clarification: structure only (2026-09-09)

[KNOWN | HIGH] The user clarified that a template means a Prompt structure, not insurance
or stage-specific instructions. Removed the selector and business template content; the
single insert button now appends only the three named sections with neutral fill-in hints.

RED: the new test rejected the existing business-template selector. GREEN: 105 tests in
WorkflowModuleEditor, AgentDetailPage and agentYaml passed; `npm run build:dashboard`
passed. Browser inspection of the actual component in a synthetic page confirmed the
three exact headings, editable hints and absence of the selector. Final desktop screenshot
was inspected. Earlier backend tests remain applicable because this correction changes
no backend behavior; earlier screenshots/business-template checks are superseded.

Updated code/test fingerprints below describe the corrected implementation. Temporary
fixture and browser space were cleaned up. No live Agent configuration was edited.
