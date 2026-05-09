import typer

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
    typer.echo(f"Comparing {agent_yaml}: {question}")


def main() -> None:
    app()
