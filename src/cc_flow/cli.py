"""CLI entry point for cc-flow."""

import tempfile
import webbrowser
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)


@app.command()
def main(
    jsonl_path: Path = typer.Argument(..., help="Path to JSONL transcript file"),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output HTML file path"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open in browser"),
) -> None:
    """Visualize a Claude Code session as interactive HTML."""
    from .parser import parse_session
    from .renderer import render

    if not jsonl_path.exists():
        typer.echo(f"Error: File not found: {jsonl_path}", err=True)
        raise typer.Exit(1)

    session = parse_session(jsonl_path)
    html = render(session)

    if output is None:
        output = Path(tempfile.mktemp(suffix=".html", prefix="cc-flow-"))

    output.write_text(html)
    typer.echo(f"Written to {output}")

    if not no_open:
        webbrowser.open(f"file://{output}")


if __name__ == "__main__":
    app()
