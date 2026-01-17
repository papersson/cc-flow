"""Unit tests for the parser module."""

from pathlib import Path

import pytest

from cc_flow.models import BlockType
from cc_flow.parser import (
    build_segments,
    get_content_blocks,
    is_user_text,
    load_records,
    parse_session,
    truncate,
)


class TestLoadRecords:
    """Tests for load_records function."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        records = load_records(f)
        assert records == []

    def test_filters_file_history_snapshot(self, tmp_path: Path) -> None:
        """File history snapshot records are filtered out."""
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"type": "file-history-snapshot", "uuid": "1"}\n{"type": "user", "uuid": "2"}\n'
        )
        records = load_records(f)
        assert len(records) == 1
        assert records[0]["type"] == "user"

    def test_filters_progress(self, tmp_path: Path) -> None:
        """Progress records are filtered out."""
        f = tmp_path / "test.jsonl"
        f.write_text('{"type": "progress", "uuid": "1"}\n{"type": "user", "uuid": "2"}\n')
        records = load_records(f)
        assert len(records) == 1
        assert records[0]["type"] == "user"

    def test_skips_malformed_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Malformed JSON lines are skipped with warning."""
        f = tmp_path / "test.jsonl"
        f.write_text('{"type": "user"}\nnot json\n{"type": "assistant"}\n')
        records = load_records(f)
        assert len(records) == 2
        captured = capsys.readouterr()
        assert "Warning: Skipping malformed JSON at line 2" in captured.err


class TestHelpers:
    """Tests for helper functions."""

    def test_get_content_blocks_string(self) -> None:
        """String content is wrapped in text block."""
        blocks = get_content_blocks({"content": "hello"})
        assert blocks == [{"type": "text", "text": "hello"}]

    def test_get_content_blocks_list(self) -> None:
        """List content is returned as-is."""
        content = [{"type": "text", "text": "hello"}]
        blocks = get_content_blocks({"content": content})
        assert blocks == content

    def test_truncate_short(self) -> None:
        """Short text is not truncated."""
        assert truncate("hello", 100) == "hello"

    def test_truncate_long(self) -> None:
        """Long text is truncated with ellipsis."""
        result = truncate("a" * 500, 100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_is_user_text_true(self) -> None:
        """User text message returns True."""
        rec = {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}
        assert is_user_text(rec) is True

    def test_is_user_text_tool_result(self) -> None:
        """Tool result message returns False."""
        rec = {"type": "user", "message": {"content": [{"type": "tool_result"}]}}
        assert is_user_text(rec) is False

    def test_is_user_text_assistant(self) -> None:
        """Assistant message returns False."""
        rec = {"type": "assistant", "message": {"content": [{"type": "text"}]}}
        assert is_user_text(rec) is False


class TestParseSession:
    """Tests for parse_session function."""

    def test_simple_session(self, simple_session: Path) -> None:
        """Parse simple session correctly."""
        session = parse_session(simple_session)
        assert len(session.segments) == 1
        segment = session.segments[0]
        assert segment.type == "original"
        assert len(segment.turns) == 2  # Two user messages -> two turns

    def test_session_with_branches(self, with_branches_session: Path) -> None:
        """Parse session with branches correctly."""
        session = parse_session(with_branches_session)
        assert len(session.segments) == 1
        segment = session.segments[0]
        # First turn has two children (branches)
        assert len(segment.turns) == 3

    def test_session_with_compaction(self, with_compaction_session: Path) -> None:
        """Parse session with compaction correctly."""
        session = parse_session(with_compaction_session)
        assert len(session.segments) == 2
        assert session.segments[0].type == "original"
        assert session.segments[1].type == "continuation"
        assert session.segments[1].compact_metadata is not None
        assert session.segments[1].compact_metadata.pre_tokens == 162000

    def test_session_with_subagent(self, with_subagent_session: Path) -> None:
        """Parse session with subagent correctly."""
        session = parse_session(with_subagent_session)
        assert len(session.segments) == 1
        segment = session.segments[0]
        assert len(segment.turns) == 1
        # Check that tool_use block has child_agent_id linked
        turn = segment.turns[0]
        tool_use_blocks = [b for b in turn.blocks if b.type == BlockType.TOOL_USE]
        assert len(tool_use_blocks) == 1
        assert tool_use_blocks[0].child_agent_id == "abc123def"


class TestBuildSegments:
    """Tests for build_segments function."""

    def test_empty_records(self) -> None:
        """Empty records returns empty segments."""
        segments = build_segments([])
        assert segments == []

    def test_single_user_message(self) -> None:
        """Single user message creates one segment with one turn."""
        records = [
            {
                "uuid": "1",
                "type": "user",
                "timestamp": "2026-01-17T10:00:00Z",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        ]
        segments = build_segments(records)
        assert len(segments) == 1
        assert len(segments[0].turns) == 1

    def test_user_and_assistant(self) -> None:
        """User + assistant creates one turn with blocks."""
        records = [
            {
                "uuid": "1",
                "type": "user",
                "timestamp": "2026-01-17T10:00:00Z",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            },
            {
                "uuid": "2",
                "type": "assistant",
                "parentUuid": "1",
                "timestamp": "2026-01-17T10:00:05Z",
                "message": {"content": [{"type": "text", "text": "hi there"}]},
            },
        ]
        segments = build_segments(records)
        assert len(segments) == 1
        assert len(segments[0].turns) == 1
        assert len(segments[0].turns[0].blocks) == 1
        assert segments[0].turns[0].blocks[0].type == BlockType.TEXT
