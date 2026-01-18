"""Unit tests for the parser module."""

from pathlib import Path

import pytest

from cc_flow.models import BlockType
from cc_flow.parser import (
    build_segments,
    get_content_blocks,
    is_image_placeholder,
    is_system_message,
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

    def test_session_with_images(self, with_images_session: Path) -> None:
        """Parse session with image attachments correctly."""
        session = parse_session(with_images_session)
        assert len(session.segments) == 1
        segment = session.segments[0]

        # Should have 2 turns: original message + follow-up with embedded image
        # Image placeholder records should be filtered out
        assert len(segment.turns) == 2

        # First turn should have collected image paths from child placeholder records
        turn1 = segment.turns[0]
        assert turn1.user_message == "Check this screenshot of the bug"
        assert len(turn1.image_paths) == 2
        assert "/tmp/screenshot1.png" in turn1.image_paths
        assert "/tmp/screenshot2.png" in turn1.image_paths

        # Second turn has embedded image (text + image block), should not be filtered
        turn2 = segment.turns[1]
        assert turn2.user_message == "Here's another one"
        # No separate image placeholder children, so no paths collected this way
        assert len(turn2.image_paths) == 0


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


class TestIsImagePlaceholder:
    """Tests for is_image_placeholder detection."""

    def test_text_placeholder_detected(self) -> None:
        """[Image: source:...] text is detected as placeholder."""
        rec = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "[Image: source: /path/to/img.png]"}]},
        }
        assert is_image_placeholder(rec) is True

    def test_image_only_record_detected(self) -> None:
        """Record with only image blocks (no text) is placeholder."""
        rec = {
            "type": "user",
            "message": {
                "content": [{"type": "image", "source": {"type": "base64", "data": "abc"}}]
            },
        }
        assert is_image_placeholder(rec) is True

    def test_image_with_placeholder_text_detected(self) -> None:
        """Image record with [Image: source:] text is placeholder."""
        rec = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "[Image: source: /tmp/img.png]"},
                    {"type": "image", "source": {"type": "base64", "data": "abc"}},
                ]
            },
        }
        assert is_image_placeholder(rec) is True

    def test_image_prefix_but_not_source_is_real(self) -> None:
        """Text starting with [Image: but not [Image: source: is real message."""
        rec = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "[Image: I think this looks good]"}]},
        }
        assert is_image_placeholder(rec) is False

    def test_text_with_image_is_real(self) -> None:
        """Record with meaningful text AND image is real message."""
        rec = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Here's a screenshot of the bug"},
                    {"type": "image", "source": {"type": "base64", "data": "abc"}},
                ]
            },
        }
        assert is_image_placeholder(rec) is False

    def test_regular_text_not_placeholder(self) -> None:
        """Regular user text is not a placeholder."""
        rec = {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "Hello, can you help?"}]},
        }
        assert is_image_placeholder(rec) is False

    def test_assistant_never_placeholder(self) -> None:
        """Assistant records are never placeholders."""
        rec = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "[Image: source: /path]"}]},
        }
        assert is_image_placeholder(rec) is False

    def test_empty_content_not_placeholder(self) -> None:
        """Empty content is not a placeholder."""
        rec = {"type": "user", "message": {"content": []}}
        assert is_image_placeholder(rec) is False


class TestIsSystemMessage:
    """Tests for is_system_message detection."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("This session is being continued from a previous conversation", True),
            ("<local-command>ls</local-command>", True),
            ("<command-name>/help</command-name>", True),
            ("<command-message>clear</command-message>", True),
            ("<system-reminder>Remember to use tools</system-reminder>", True),
            ("[Request interrupted by user]", True),
            ("[Image: source: /path/to/file.png]", True),
            ("Hello, can you help me with this code?", False),
            ("This session was really helpful", False),  # Starts with "This session" but not the magic prefix
            ("Check this image I found", False),
            ("[Something else in brackets]", False),
        ],
    )
    def test_system_message_detection(self, text: str, expected: bool) -> None:
        """Verify system message prefixes are detected correctly."""
        assert is_system_message(text) is expected


class TestBlockTruncation:
    """Tests for block truncation with full_content preservation."""

    def test_thinking_truncated_at_500(self) -> None:
        """Thinking blocks truncate at 500 chars."""
        long_thinking = "x" * 600
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
                "message": {"content": [{"type": "thinking", "thinking": long_thinking}]},
            },
        ]
        segments = build_segments(records)
        block = segments[0].turns[0].blocks[0]
        assert block.type == BlockType.THINKING
        assert block.is_truncated is True
        assert len(block.content) == 503  # 500 + "..."
        assert block.full_content == long_thinking

    def test_thinking_not_truncated_under_500(self) -> None:
        """Thinking under 500 chars is not truncated."""
        short_thinking = "x" * 400
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
                "message": {"content": [{"type": "thinking", "thinking": short_thinking}]},
            },
        ]
        segments = build_segments(records)
        block = segments[0].turns[0].blocks[0]
        assert block.type == BlockType.THINKING
        assert block.is_truncated is False
        assert block.content == short_thinking
        assert block.full_content is None

    def test_tool_input_truncated_at_200(self) -> None:
        """Tool input truncates at 200 chars."""
        long_command = "echo " + "x" * 250
        records = [
            {
                "uuid": "1",
                "type": "user",
                "timestamp": "2026-01-17T10:00:00Z",
                "message": {"content": [{"type": "text", "text": "run a command"}]},
            },
            {
                "uuid": "2",
                "type": "assistant",
                "parentUuid": "1",
                "timestamp": "2026-01-17T10:00:05Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool1",
                            "name": "Bash",
                            "input": {"command": long_command},
                        }
                    ]
                },
            },
        ]
        segments = build_segments(records)
        block = segments[0].turns[0].blocks[0]
        assert block.type == BlockType.TOOL_USE
        assert block.is_truncated is True
        assert len(block.tool_input) == 203  # 200 + "..."
        assert block.full_content == long_command

    def test_tool_result_truncated_at_300(self) -> None:
        """Tool result truncates at 300 chars."""
        long_result = "output: " + "y" * 350
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
                "message": {
                    "content": [{"type": "tool_use", "id": "tool1", "name": "Bash", "input": {}}]
                },
            },
            {
                "uuid": "3",
                "type": "user",
                "parentUuid": "2",
                "timestamp": "2026-01-17T10:00:10Z",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "tool1", "content": long_result}]
                },
            },
        ]
        segments = build_segments(records)
        result_blocks = [b for b in segments[0].turns[0].blocks if b.type == BlockType.TOOL_RESULT]
        assert len(result_blocks) == 1
        block = result_blocks[0]
        assert block.is_truncated is True
        assert len(block.content) == 303  # 300 + "..."
        assert block.full_content == long_result
