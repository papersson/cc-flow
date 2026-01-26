"""HTML renderer for session visualization."""

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .models import Session


def image_to_data_url(path: str) -> str | None:
    """Read an image file and convert to base64 data URL."""
    try:
        file_path = Path(path)
        if not file_path.exists():
            return None

        # Guess MIME type
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type is None:
            mime_type = "image/png"  # Default fallback

        # Read and encode
        data = file_path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime_type};base64,{b64}"
    except (OSError, PermissionError):
        return None


def json_for_html(data: Any) -> str:
    """Safely encode JSON for embedding in HTML script tags."""
    json_str = json.dumps(data, ensure_ascii=False)
    # Escape </script> and <!-- to prevent HTML injection
    json_str = json_str.replace("</script>", "</scr\\u0069pt>")
    json_str = json_str.replace("<!--", "<\\u0021--")
    return json_str


def process_images(paths: list[str], embed: bool) -> list[dict]:
    """Process image paths, optionally embedding as data URLs."""
    images = []
    for path in paths:
        img = {"path": path}
        if embed:
            data_url = image_to_data_url(path)
            if data_url:
                img["data_url"] = data_url
        images.append(img)
    return images


def session_to_dict(session: Session, embed_images: bool = False) -> dict:
    """Convert Session model to dict for JSON serialization."""
    segments = []
    for seg in session.segments:
        turns = []
        for turn in seg.turns:
            blocks = []
            for block in turn.blocks:
                blocks.append(
                    {
                        "type": block.type.value,
                        "content": block.content,
                        "timestamp": block.timestamp,
                        "tool_name": block.tool_name,
                        "tool_input": block.tool_input,
                        "tool_use_id": block.tool_use_id,
                        "child_agent_id": block.child_agent_id,
                        "subagent_type": block.subagent_type,
                        "full_content": block.full_content,
                        "is_truncated": block.is_truncated,
                    }
                )
            turns.append(
                {
                    "id": turn.id,
                    "user_message": turn.user_message,
                    "user_timestamp": turn.user_timestamp,
                    "blocks": blocks,
                    "parent_turn_id": turn.parent_turn_id,
                    "children_turn_ids": turn.children_turn_ids,
                    "is_branch": turn.is_branch,
                    "is_system": turn.is_system,
                    "images": process_images(turn.image_paths, embed_images),
                }
            )
        segments.append(
            {
                "id": seg.id,
                "type": seg.type,
                "timestamp": seg.timestamp,
                "turns": turns,
                "compact_metadata": {
                    "trigger": seg.compact_metadata.trigger,
                    "pre_tokens": seg.compact_metadata.pre_tokens,
                }
                if seg.compact_metadata
                else None,
            }
        )

    # Convert subagents
    subagents = {}
    for agent_id, turns in session.subagents.items():
        agent_turns = []
        for turn in turns:
            blocks = []
            for block in turn.blocks:
                blocks.append(
                    {
                        "type": block.type.value,
                        "content": block.content,
                        "timestamp": block.timestamp,
                        "tool_name": block.tool_name,
                        "tool_input": block.tool_input,
                        "tool_use_id": block.tool_use_id,
                        "child_agent_id": block.child_agent_id,
                        "subagent_type": block.subagent_type,
                        "full_content": block.full_content,
                        "is_truncated": block.is_truncated,
                    }
                )
            agent_turns.append(
                {
                    "id": turn.id,
                    "user_message": turn.user_message,
                    "user_timestamp": turn.user_timestamp,
                    "blocks": blocks,
                    "parent_turn_id": turn.parent_turn_id,
                    "children_turn_ids": turn.children_turn_ids,
                    "is_branch": turn.is_branch,
                    "is_system": turn.is_system,
                    "images": process_images(turn.image_paths, embed_images),
                }
            )
        subagents[agent_id] = agent_turns

    return {
        "segments": segments,
        "subagents": subagents,
    }


def compute_metadata(session: Session, jsonl_path: Path) -> dict:
    """Compute summary metadata for the session."""
    total_turns = sum(len(seg.turns) for seg in session.segments)
    compactions = sum(1 for seg in session.segments if seg.compact_metadata)

    # Get earliest timestamp from first segment's first turn
    started = None
    if session.segments and session.segments[0].turns:
        started = session.segments[0].turns[0].user_timestamp

    return {
        "session_id": jsonl_path.stem,
        "started": started,
        "total_turns": total_turns,
        "total_subagents": len(session.subagents),
        "compactions": compactions,
    }


def render_json(session: Session, jsonl_path: Path, compact: bool = False) -> str:
    """Render session as JSON string."""
    data = session_to_dict(session)
    metadata = compute_metadata(session, jsonl_path)

    # Put metadata first in output
    ordered = {"metadata": metadata, **data}

    return json.dumps(ordered, indent=None if compact else 2)


def load_assets() -> dict[str, str]:
    """Load bundled JS/CSS assets for inline embedding."""
    assets_dir = Path(__file__).parent / "assets"
    assets = {}

    for name in [
        "marked.min.js",
        "highlight.min.js",
        "hljs-github-dark.min.css",
        "styles.css",
        "app.js",
    ]:
        asset_path = assets_dir / name
        if asset_path.exists():
            assets[name.replace(".", "_").replace("-", "_")] = asset_path.read_text()
        else:
            assets[name.replace(".", "_").replace("-", "_")] = ""

    return assets


def render(session: Session, embed_images: bool = False) -> str:
    """Render Session to self-contained HTML string."""
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=False)
    template = env.get_template("base.html.j2")

    data = session_to_dict(session, embed_images=embed_images)
    session_json = json_for_html(data)
    assets = load_assets()

    return template.render(session_json=session_json, **assets)
