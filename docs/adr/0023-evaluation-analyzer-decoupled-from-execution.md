# ADR-0023: Evaluation Analyzer Decoupled from Execution

## Status

Accepted

## Context

Proof Agent needs trustworthy post-run evaluation of Agent behavior, including governed resolution, Control Envelope coverage, evidence support, tool governance, response projection safety, and audit artifact sufficiency. The earlier evaluation plan used a CLI runner shape that both produced Agent runs and evaluated them, which was convenient for smoke testing but made Evaluation look like a new execution path.

## Decision

Evaluation Analysis is post-run only. The Evaluation Analyzer reads existing governed run artifacts and audience-safe response projections through an Evaluation Subject Manifest or frozen Evaluation Subject Export, then writes Evaluation Artifact Set files. It must not create Agent runs, call models, retrieve knowledge, execute tools, invoke PolicyEngine, or depend on Runtime, Control Workflow, Capability, or Bootstrap execution paths.

Evaluation Run Producer is a separate optional helper. It may create governed sample runs only by calling existing execution surfaces, such as Direct Harness, Run Execution API, or Customer Run API, and then export an Evaluation Subject Manifest. Dashboard and RunStore may export Evaluation Subjects, including frozen bundles, but they do not own evaluation semantics.

## Consequences

- Evaluation Store contains analysis artifacts only: Evaluation Report, Evaluation Result JSONL, and Evaluation Analysis Receipt.
- Agent run artifacts remain ordinary governed run artifacts, preferably marked with `run_purpose: evaluation_sample` when produced for evaluation sampling.
- Release and safety analysis must use explicit, immutable artifact references with hashes; `runs/latest` and mutable Dashboard endpoints are not valid formal Evaluation Subjects.
- Evaluation Analyzer can fail cases for missing subjects or insufficient artifacts, but it cannot infer governance success from incomplete traces.
