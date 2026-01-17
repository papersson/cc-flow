"""JSONL parser for Claude Code transcripts."""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from .models import Block, BlockType, CompactMetadata, Segment, Session, Turn


def load_records(path: Path) -> list[dict]:
    """Load JSONL, skip file-history-snapshot and progress records."""
    records = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("type") not in ["file-history-snapshot", "progress"]:
                    records.append(rec)
            except json.JSONDecodeError as e:
                print(f"Warning: Skipping malformed JSON at line {line_num}: {e}", file=sys.stderr)
    return records


def get_content_blocks(message: dict) -> list[dict]:
    """Extract content blocks from message."""
    content = message.get("content", [])
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def truncate(text: str, max_len: int = 300) -> str:
    """Truncate text with ellipsis."""
    text = str(text)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def extract_agent_id_from_result(content: list | str) -> str | None:
    """Extract agentId from tool result content."""
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                match = re.search(r"agentId:\s*([a-f0-9]+)", text)
                if match:
                    return match.group(1)
    return None


def build_tree(records: list[dict]) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Build uuid -> record lookup and children map."""
    by_uuid = {r.get("uuid"): r for r in records if r.get("uuid")}
    children_map: dict[str, list[str]] = defaultdict(list)

    for rec in records:
        parent = rec.get("parentUuid")
        uuid = rec.get("uuid")
        if parent and uuid:
            children_map[parent].append(uuid)

    # Sort children by timestamp
    for _parent, kids in children_map.items():
        kids.sort(key=lambda u: by_uuid.get(u, {}).get("timestamp", ""))

    return by_uuid, children_map


def find_roots(records: list[dict], by_uuid: dict[str, dict]) -> list[str]:
    """Find records with no parent in dataset."""
    roots = []
    for rec in records:
        uuid = rec.get("uuid")
        parent = rec.get("parentUuid")
        if uuid and (not parent or parent not in by_uuid):
            roots.append(uuid)
    return roots


def is_user_text(rec: dict) -> bool:
    """Check if record is user message (not tool_result)."""
    if rec.get("type") != "user":
        return False
    blocks = get_content_blocks(rec.get("message", {}))
    if not blocks:
        return False
    return blocks[0].get("type") not in ["tool_result"]


def is_system_message(text: str) -> bool:
    """Check if a user message is actually a system-injected message by content."""
    system_prefixes = [
        "This session is being continued",
        "<local-command",
        "<command-name>",
        "<command-message>",
        "<system-reminder>",
        "[Request interrupted",
        "[Image: source:",
    ]
    for prefix in system_prefixes:
        if text.startswith(prefix):
            return True
    return False


def is_system_record(rec: dict) -> bool:
    """Check if a record is a system message using JSONL fields or content."""
    # Use JSONL fields if available
    if rec.get("isCompactSummary") or rec.get("isVisibleInTranscriptOnly"):
        return True
    # Fall back to content-based detection
    blocks = get_content_blocks(rec.get("message", {}))
    if blocks and blocks[0].get("type") == "text":
        text = blocks[0].get("text", "")
        return is_system_message(text)
    return False


def collect_turns(
    start_uuid: str,
    by_uuid: dict[str, dict],
    children_map: dict[str, list[str]],
) -> list[Turn]:
    """BFS traversal to collect turns from a starting user message."""
    turns: list[Turn] = []
    turn_counter = [0]

    def collect_turn(uuid: str, parent_turn_id: int | None = None) -> Turn | None:
        rec = by_uuid.get(uuid)
        if not rec or not is_user_text(rec):
            return None

        current_turn_id = turn_counter[0]
        turn_counter[0] += 1

        # Extract user message
        user_message = ""
        blocks = get_content_blocks(rec.get("message", {}))
        for block in blocks:
            if block.get("type") == "text":
                user_message = block.get("text", "")
                break

        turn = Turn(
            id=current_turn_id,
            user_message=user_message,
            user_timestamp=rec.get("timestamp", ""),
            parent_turn_id=parent_turn_id,
            is_system=is_system_record(rec),
        )

        response_blocks: list[Block] = []
        child_turn_ids: list[int] = []

        # BFS to collect all response items and find next user text messages
        visited = {uuid}
        queue = list(children_map.get(uuid, []))
        found_user_texts: list[str] = []

        while queue:
            kid_uuid = queue.pop(0)
            if kid_uuid in visited:
                continue
            visited.add(kid_uuid)

            kid_rec = by_uuid.get(kid_uuid)
            if not kid_rec:
                continue

            if is_user_text(kid_rec):
                found_user_texts.append(kid_uuid)
                continue

            kid_blocks = get_content_blocks(kid_rec.get("message", {}))

            for block in kid_blocks:
                block_type = block.get("type")
                timestamp = kid_rec.get("timestamp", "")[11:19] if kid_rec.get("timestamp") else ""

                if block_type == "thinking":
                    response_blocks.append(
                        Block(
                            type=BlockType.THINKING,
                            content=truncate(block.get("thinking", ""), 500),
                            timestamp=timestamp,
                        )
                    )
                elif block_type == "text":
                    response_blocks.append(
                        Block(
                            type=BlockType.TEXT,
                            content=block.get("text", ""),
                            timestamp=timestamp,
                        )
                    )
                elif block_type == "tool_use":
                    inputs = block.get("input", {})
                    tool_input = ""
                    for key in ["command", "prompt", "pattern", "file_path", "query"]:
                        if key in inputs:
                            tool_input = truncate(str(inputs[key]), 200)
                            break
                    else:
                        tool_input = truncate(str(inputs), 100)

                    response_blocks.append(
                        Block(
                            type=BlockType.TOOL_USE,
                            content="",
                            timestamp=timestamp,
                            tool_name=block.get("name", "?"),
                            tool_input=tool_input,
                            tool_use_id=block.get("id", ""),
                            subagent_type=inputs.get("subagent_type"),
                        )
                    )
                elif block_type == "tool_result":
                    content = block.get("content", "")
                    agent_id = extract_agent_id_from_result(content)
                    if isinstance(content, list):
                        texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                        content = "\n".join(texts)
                    response_blocks.append(
                        Block(
                            type=BlockType.TOOL_RESULT,
                            content=truncate(str(content), 300),
                            timestamp=timestamp,
                            tool_use_id=block.get("tool_use_id", ""),
                            child_agent_id=agent_id,
                        )
                    )

            for child in children_map.get(kid_uuid, []):
                if child not in visited:
                    queue.append(child)

        # Sort blocks by timestamp
        response_blocks.sort(key=lambda x: x.timestamp or "")

        # Link agent IDs from tool_result to tool_use
        for i, block in enumerate(response_blocks):
            if block.type == BlockType.TOOL_RESULT and block.child_agent_id:
                tool_use_id = block.tool_use_id
                for j in range(i - 1, -1, -1):
                    prev = response_blocks[j]
                    if prev.type == BlockType.TOOL_USE and prev.tool_use_id == tool_use_id:
                        prev.child_agent_id = block.child_agent_id
                        break

        turn.blocks = response_blocks

        # Recursively collect child turns
        for user_uuid in found_user_texts:
            child_turn = collect_turn(user_uuid, current_turn_id)
            if child_turn:
                child_turn_ids.append(child_turn.id)
                turns.append(child_turn)

        turn.children_turn_ids = child_turn_ids

        # Mark as branch if multiple children
        if len(found_user_texts) > 1:
            for child_id in child_turn_ids:
                for t in turns:
                    if t.id == child_id:
                        t.is_branch = True

        return turn

    root_turn = collect_turn(start_uuid)
    if root_turn:
        turns.insert(0, root_turn)
    return turns


def find_first_user_text(
    start_uuid: str,
    by_uuid: dict[str, dict],
    children_map: dict[str, list[str]],
) -> str | None:
    """BFS to find the first valid user_text message."""
    visited = set()
    queue = [start_uuid]

    while queue:
        uuid = queue.pop(0)
        if uuid in visited:
            continue
        visited.add(uuid)

        rec = by_uuid.get(uuid)
        if rec and is_user_text(rec):
            return uuid

        # Add children to queue
        for child_uuid in children_map.get(uuid, []):
            if child_uuid not in visited:
                queue.append(child_uuid)

    return None


def build_segments(records: list[dict]) -> list[Segment]:
    """Group turns into segments based on compact_boundary."""
    by_uuid, children_map = build_tree(records)
    roots = find_roots(records, by_uuid)

    segments: list[Segment] = []

    for root_uuid in roots:
        root_rec = by_uuid.get(root_uuid)
        if not root_rec:
            continue

        root_subtype = root_rec.get("subtype", "")
        compact_meta = root_rec.get("compactMetadata", {})
        timestamp = root_rec.get("timestamp", "")

        # Find the starting user_text for this segment (BFS search)
        if is_user_text(root_rec):
            start_uuid = root_uuid
            segment_type = "original"
        elif root_subtype == "compact_boundary":
            start_uuid = find_first_user_text(root_uuid, by_uuid, children_map)
            segment_type = "continuation"
        else:
            start_uuid = find_first_user_text(root_uuid, by_uuid, children_map)
            segment_type = "original"

        if not start_uuid:
            continue

        turns = collect_turns(start_uuid, by_uuid, children_map)
        if not turns:
            continue

        segment = Segment(
            id=len(segments),
            type=segment_type,
            timestamp=timestamp,
            turns=turns,
        )

        if compact_meta:
            segment.compact_metadata = CompactMetadata(
                trigger=compact_meta.get("trigger", "unknown"),
                pre_tokens=compact_meta.get("preTokens", 0),
            )

        segments.append(segment)

    # Sort segments by timestamp and re-number
    segments.sort(key=lambda s: s.timestamp)
    for i, seg in enumerate(segments):
        seg.id = i

    return segments


def load_subagents(session_dir: Path) -> dict[str, list[Turn]]:
    """Load all subagent JSONL files from subagents/ directory."""
    subagents: dict[str, list[Turn]] = {}
    subagent_dir = session_dir / "subagents"

    if not subagent_dir.exists():
        return subagents

    for f in subagent_dir.glob("*.jsonl"):
        agent_id = f.stem.replace("agent-", "")
        records = load_records(f)
        segments = build_segments(records)
        # Flatten turns from all segments
        all_turns = []
        for seg in segments:
            all_turns.extend(seg.turns)
        subagents[agent_id] = all_turns

    return subagents


def parse_session(jsonl_path: Path) -> Session:
    """Main entry point: JSONL path -> Session model."""
    records = load_records(jsonl_path)

    if not records:
        return Session(segments=[], subagents={})

    segments = build_segments(records)

    # Load subagents from session directory
    session_id = jsonl_path.stem
    session_dir = jsonl_path.parent / session_id
    subagents = load_subagents(session_dir)

    return Session(segments=segments, subagents=subagents)
