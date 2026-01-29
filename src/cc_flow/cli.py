"""CLI entry point for cc-flow."""

import tempfile
import webbrowser
from pathlib import Path

import typer

APP_HELP = """
Visualize Claude Code session transcripts.

\b
Session files are stored at:
  ~/.claude/projects/<project-hash>/sessions/<session-id>.jsonl

\b
To find recent sessions:
  ls -lt ~/.claude/projects/*/sessions/*.jsonl | head
"""

HTML_HELP = """
Render session as interactive HTML and open in browser.

The HTML viewer provides collapsible turns, syntax-highlighted code blocks,
searchable content, and navigation for branches and subagents.

\b
Session files are stored at:
  ~/.claude/projects/<project-hash>/sessions/<session-id>.jsonl

\b
Also accepts JSON output from the transcript command:
  cc-flow transcript session.jsonl -o session.json
  cc-flow html session.json

\b
Examples:
  # Open most recent session
  cc-flow html $(ls -t ~/.claude/projects/*/sessions/*.jsonl | head -1)

  # Save to specific file without opening browser
  cc-flow html session.jsonl -o report.html --no-open
"""

app = typer.Typer(add_completion=False, help=APP_HELP)


@app.command(help=HTML_HELP)
def html(
    input_path: Path = typer.Argument(..., help="Path to JSONL transcript or JSON file"),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output HTML file path"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open in browser"),
    embed_images: bool = typer.Option(
        False, "--embed-images", help="Embed images as base64 (increases file size)"
    ),
) -> None:
    import json

    from .parser import parse_session
    from .renderer import dict_to_session, render

    if not input_path.exists():
        typer.echo(f"Error: File not found: {input_path}", err=True)
        raise typer.Exit(1)

    if input_path.suffix == ".json":
        data = json.loads(input_path.read_text())
        session = dict_to_session(data)
    else:
        session = parse_session(input_path)

    html_content = render(session, embed_images=embed_images)

    if output is None:
        output = Path(tempfile.mktemp(suffix=".html", prefix="cc-flow-"))

    output.write_text(html_content)
    typer.echo(f"Written to {output}")

    if not no_open:
        webbrowser.open(f"file://{output}")


TRANSCRIPT_HELP = """
Output parsed session as clean JSON for programmatic querying.

Unlike raw JSONL transcripts, this output has the tree structure resolved,
subagents linked to parent turns, and noise removed (usage stats, cache metadata).

\b
Session files are stored at:
  ~/.claude/projects/<project-hash>/sessions/<session-id>.jsonl

\b
Examples:
  # Get session metadata
  cc-flow transcript session.jsonl | jq '.metadata'

  # Get a specific turn (turn 5 in first segment)
  cc-flow transcript session.jsonl | jq '.segments[0].turns[5]'

  # List all tool calls
  cc-flow transcript session.jsonl | jq '[.segments[].turns[].blocks[] | select(.type == "tool_use") | {tool: .tool_name, input: .tool_input}]'

  # Get all Bash commands
  cc-flow transcript session.jsonl | jq '[.segments[].turns[].blocks[] | select(.tool_name == "Bash") | .tool_input]'

  # Conversation overview (turn IDs and truncated user messages)
  cc-flow transcript session.jsonl | jq '[.segments[].turns[] | {turn: .id, user: .user_message[:80]}]'

  # List subagent IDs
  cc-flow transcript session.jsonl | jq '.subagents | keys'

  # Get specific subagent transcript
  cc-flow transcript session.jsonl | jq '.subagents["agent-abc123"]'

  # Count tokens before compaction
  cc-flow transcript session.jsonl | jq '[.segments[].compact_metadata | select(.) | .pre_tokens]'

  # Compact output for piping (no indentation)
  cc-flow transcript session.jsonl --compact | jq '.metadata.total_turns'

\b
Output structure:
  {
    "metadata": {
      "session_id": "...",
      "started": "2026-01-25T10:00:00Z",
      "total_turns": 47,
      "total_subagents": 3,
      "compactions": 1
    },
    "segments": [...],    # Conversation segments (split at compaction boundaries)
    "subagents": {...}    # Subagent transcripts keyed by agent ID
  }
"""


@app.command(help=TRANSCRIPT_HELP)
def transcript(
    jsonl_path: Path = typer.Argument(..., help="Path to JSONL transcript file"),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output JSON file path"),
    compact: bool = typer.Option(False, "--compact", help="No indentation (for piping)"),
) -> None:
    from .parser import parse_session
    from .renderer import render_json

    if not jsonl_path.exists():
        typer.echo(f"Error: File not found: {jsonl_path}", err=True)
        raise typer.Exit(1)

    session = parse_session(jsonl_path)
    json_str = render_json(session, jsonl_path, compact=compact)

    if output is None:
        typer.echo(json_str)
    else:
        output.write_text(json_str)
        typer.echo(f"Written to {output}", err=True)


if __name__ == "__main__":
    app()
