import typer

from proof_agent.compare.harness_rag import run_harness_rag
from proof_agent.compare.plain_rag import run_plain_rag

app = typer.Typer(no_args_is_help=True)


@app.command()
def demo() -> None:
    typer.echo("Proof Agent demo")


@app.command()
def run(agent_yaml: str) -> None:
    typer.echo(f"Running {agent_yaml}")


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
