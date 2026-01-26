"""Property-based tests using Hypothesis."""

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from cc_flow.models import BlockType
from cc_flow.parser import build_segments, load_records, truncate


# Custom strategies
@st.composite
def user_record(draw: st.DrawFn) -> dict:
    """Generate a user record."""
    return {
        "uuid": draw(st.text(alphabet="abcdef0123456789", min_size=8, max_size=8)),
        "type": "user",
        "timestamp": "2026-01-17T10:00:00Z",
        "message": {"content": [{"type": "text", "text": draw(st.text(min_size=1, max_size=100))}]},
    }


@st.composite
def assistant_record(draw: st.DrawFn, parent_uuid: str) -> dict:
    """Generate an assistant record."""
    return {
        "uuid": draw(st.text(alphabet="abcdef0123456789", min_size=8, max_size=8)),
        "type": "assistant",
        "parentUuid": parent_uuid,
        "timestamp": "2026-01-17T10:00:05Z",
        "message": {"content": [{"type": "text", "text": draw(st.text(min_size=1, max_size=100))}]},
    }


@st.composite
def thinking_block(draw: st.DrawFn) -> dict:
    """Generate a thinking block with variable length content."""
    # Generate content that may or may not exceed truncation threshold (500)
    content = draw(
        st.text(min_size=1, max_size=700, alphabet=st.characters(blacklist_categories=("Cs",)))
    )
    return {"type": "thinking", "thinking": content}


@st.composite
def tool_use_block(draw: st.DrawFn) -> dict:
    """Generate a tool_use block with variable length input."""
    # Generate input that may or may not exceed truncation threshold (200)
    command = draw(
        st.text(min_size=1, max_size=350, alphabet=st.characters(blacklist_categories=("Cs",)))
    )
    tool_id = draw(st.text(alphabet="abcdef0123456789", min_size=8, max_size=8))
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": "Bash",
        "input": {"command": command},
    }


@st.composite
def assistant_with_blocks(draw: st.DrawFn, parent_uuid: str) -> dict:
    """Generate an assistant record with various block types."""
    blocks = []

    # Randomly include different block types
    if draw(st.booleans()):
        blocks.append(draw(thinking_block()))
    if draw(st.booleans()):
        blocks.append(draw(tool_use_block()))
    # Always include at least one text block if no other blocks
    if not blocks or draw(st.booleans()):
        text = draw(
            st.text(min_size=1, max_size=100, alphabet=st.characters(blacklist_categories=("Cs",)))
        )
        blocks.append({"type": "text", "text": text})

    return {
        "uuid": draw(st.text(alphabet="abcdef0123456789", min_size=8, max_size=8)),
        "type": "assistant",
        "parentUuid": parent_uuid,
        "timestamp": "2026-01-17T10:00:05Z",
        "message": {"content": blocks},
    }


@st.composite
def tool_result_record(draw: st.DrawFn, parent_uuid: str, tool_use_id: str) -> dict:
    """Generate a tool_result record with variable length content."""
    # Generate content that may or may not exceed truncation threshold (300)
    content = draw(
        st.text(min_size=1, max_size=450, alphabet=st.characters(blacklist_categories=("Cs",)))
    )
    return {
        "uuid": draw(st.text(alphabet="abcdef0123456789", min_size=8, max_size=8)),
        "type": "user",
        "parentUuid": parent_uuid,
        "timestamp": "2026-01-17T10:00:10Z",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}]
        },
    }


@st.composite
def conversation_with_blocks(draw: st.DrawFn) -> list[dict]:
    """Generate a conversation with user message and assistant response containing blocks."""
    user_uuid = "user-0001"
    user = {
        "uuid": user_uuid,
        "type": "user",
        "timestamp": "2026-01-17T10:00:00Z",
        "message": {"content": [{"type": "text", "text": "Hello"}]},
    }

    assistant = draw(assistant_with_blocks(user_uuid))
    records = [user, assistant]

    # If assistant has tool_use, potentially add tool_result
    for block in assistant["message"]["content"]:
        if block.get("type") == "tool_use" and draw(st.booleans()):
            tool_result = draw(tool_result_record(assistant["uuid"], block["id"]))
            records.append(tool_result)

    return records


class TestTruncateProperties:
    """Property-based tests for truncate function."""

    @given(st.text(), st.integers(min_value=1, max_value=1000))
    def test_output_never_exceeds_limit_plus_ellipsis(self, text: str, max_len: int) -> None:
        """Output length never exceeds max_len + 3 (for ellipsis)."""
        result = truncate(text, max_len)
        assert len(result) <= max_len + 3

    @given(st.text(max_size=50))
    def test_short_text_unchanged(self, text: str) -> None:
        """Text shorter than limit is unchanged."""
        result = truncate(text, 100)
        assert result == text


class TestBuildSegmentsProperties:
    """Property-based tests for build_segments function."""

    @given(st.lists(user_record(), min_size=0, max_size=5))
    @settings(max_examples=20)
    def test_no_data_loss(self, user_records: list[dict]) -> None:
        """Every user record appears in output segments."""
        if not user_records:
            segments = build_segments([])
            assert segments == []
            return

        # Make each record independent (no parent)
        for i, rec in enumerate(user_records):
            rec["uuid"] = f"user-{i:04d}"

        segments = build_segments(user_records)

        # Count total turns
        total_turns = sum(len(seg.turns) for seg in segments)
        assert total_turns == len(user_records)


class TestLoadRecordsProperties:
    """Property-based tests for load_records function."""

    @given(
        st.lists(
            st.fixed_dictionaries(
                {
                    "type": st.sampled_from(["user", "assistant", "system"]),
                    "uuid": st.text(alphabet="abcdef0123456789", min_size=8, max_size=8),
                }
            ),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=20)
    def test_filters_correctly(self, input_records: list[dict]) -> None:
        """Filtered record types are never in output."""
        # Add some records that should be filtered
        all_records = input_records + [
            {"type": "file-history-snapshot", "uuid": "filtered1"},
            {"type": "progress", "uuid": "filtered2"},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r) for r in all_records))
            f.flush()
            result = load_records(Path(f.name))

        for rec in result:
            assert rec.get("type") not in ["file-history-snapshot", "progress"]


class TestTruncationConsistency:
    """Property tests for truncation flag consistency."""

    @given(conversation_with_blocks())
    @settings(max_examples=50)
    def test_truncation_flag_matches_full_content(self, records: list[dict]) -> None:
        """is_truncated=True ↔ full_content is not None, always.

        This invariant ensures the UI "Show all" button works correctly.
        If is_truncated is True but full_content is None, the button does nothing.
        If is_truncated is False but full_content is set, memory is wasted.
        """
        segments = build_segments(records)

        for seg in segments:
            for turn in seg.turns:
                for block in turn.blocks:
                    if block.is_truncated:
                        assert block.full_content is not None, (
                            f"Block {block.type} has is_truncated=True but full_content=None. "
                            f"Content length: {len(block.content)}"
                        )
                    else:
                        assert block.full_content is None, (
                            f"Block {block.type} has is_truncated=False but full_content is set. "
                            f"Content: {block.content[:50]}..."
                        )

    @given(conversation_with_blocks())
    @settings(max_examples=50)
    def test_truncated_content_shorter_than_full(self, records: list[dict]) -> None:
        """When truncated, displayed content should be shorter than full content."""
        segments = build_segments(records)

        for seg in segments:
            for turn in seg.turns:
                for block in turn.blocks:
                    if block.is_truncated and block.full_content:
                        # For tool_use, truncated content is in tool_input
                        if block.type == BlockType.TOOL_USE:
                            assert len(block.tool_input) < len(block.full_content)
                        else:
                            assert len(block.content) < len(block.full_content)
