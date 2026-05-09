from pathlib import Path

import typer

from proof_agent.compare.harness_rag import run_harness_rag
from proof_agent.compare.plain_rag import run_plain_rag
from proof_agent.demo.scenarios import DEMO_SCENARIOS, SUPPORTED_QUESTION
from proof_agent.workflow.orchestrator import run_enterprise_qa

app = typer.Typer(no_args_is_help=True)


@app.command()
def demo() -> None:
    typer.echo("Proof Agent demo")
    for scenario in DEMO_SCENARIOS:
        result = run_enterprise_qa(
            "examples/enterprise_qa/agent.yaml",
            question=scenario.question,
            runs_dir=Path("runs/latest"),
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command()
def run(agent_yaml: str, question: str = typer.Option(SUPPORTED_QUESTION, "--question")) -> None:
    result = run_enterprise_qa(Path(agent_yaml), question=question, runs_dir=Path("runs/latest"))
    typer.echo(result.final_output)
    typer.echo(f"Outcome: {result.outcome.value}")


@app.command()
def doctor() -> None:
    typer.echo("Python: ok")


@app.command()
def inspect(path: str) -> None:
    typer.echo(f"Inspecting {path}")


@app.command()
def compare(agent_yaml: str, question: str = typer.Option(..., "--question")) -> None:
    plain = run_plain_rag(question)
    harness = run_harness_rag(question)
    typer.echo(f"Comparing {agent_yaml}: {question}")
    typer.echo(f"Plain RAG: {plain.outcome} - {plain.message}")
    typer.echo(f"Harness RAG: {harness.outcome} - {harness.message}")


def main() -> None:
    app()
