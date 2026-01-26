"""Tests for the renderer module."""

import json
from pathlib import Path

from cc_flow.parser import parse_session
from cc_flow.renderer import (
    compute_metadata,
    image_to_data_url,
    json_for_html,
    process_images,
    render,
    render_json,
    session_to_dict,
)


class TestJsonForHtml:
    """Tests for json_for_html function."""

    def test_simple_dict(self) -> None:
        """Simple dict is serialized correctly."""
        result = json_for_html({"key": "value"})
        assert result == '{"key": "value"}'

    def test_escapes_script_tag(self) -> None:
        """Script tags are escaped."""
        result = json_for_html({"text": "</script>"})
        assert "</script>" not in result
        assert "scr\\u0069pt" in result

    def test_escapes_html_comment(self) -> None:
        """HTML comments are escaped."""
        result = json_for_html({"text": "<!--comment-->"})
        assert "<!--" not in result
        assert "<\\u0021--" in result

    def test_unicode(self) -> None:
        """Unicode is preserved."""
        result = json_for_html({"text": "Hello"})
        assert "Hello" in result


class TestSessionToDict:
    """Tests for session_to_dict function."""

    def test_simple_session(self, simple_session: Path) -> None:
        """Simple session is converted correctly."""
        session = parse_session(simple_session)
        data = session_to_dict(session)
        assert "segments" in data
        assert "subagents" in data
        assert len(data["segments"]) == 1
        assert len(data["segments"][0]["turns"]) == 2

    def test_session_with_compaction(self, with_compaction_session: Path) -> None:
        """Session with compaction includes metadata."""
        session = parse_session(with_compaction_session)
        data = session_to_dict(session)
        continuation = data["segments"][1]
        assert continuation["compact_metadata"] is not None
        assert continuation["compact_metadata"]["pre_tokens"] == 162000


class TestRender:
    """Tests for render function."""

    def test_renders_html(self, simple_session: Path) -> None:
        """Render produces valid HTML."""
        session = parse_session(simple_session)
        html = render(session)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_includes_session_data(self, simple_session: Path) -> None:
        """Rendered HTML includes session data."""
        session = parse_session(simple_session)
        html = render(session)
        assert "const data =" in html
        assert '"segments"' in html

    def test_includes_styles(self, simple_session: Path) -> None:
        """Rendered HTML includes CSS styles."""
        session = parse_session(simple_session)
        html = render(session)
        assert "<style>" in html
        assert "--coral:" in html  # Anthropic color palette

    def test_includes_scripts(self, simple_session: Path) -> None:
        """Rendered HTML includes JavaScript."""
        session = parse_session(simple_session)
        html = render(session)
        assert "<script" in html
        assert "function render()" in html

    def test_empty_session(self) -> None:
        """Empty session renders without error."""
        from cc_flow.models import Session

        session = Session(segments=[], subagents={})
        html = render(session)
        assert "<!DOCTYPE html>" in html


class TestImageToDataUrl:
    """Tests for image_to_data_url function."""

    def test_valid_png(self, tmp_path: Path) -> None:
        """Valid PNG file returns data URL with correct MIME type."""
        # Minimal valid PNG (1x1 transparent pixel)
        png_data = bytes(
            [
                0x89,
                0x50,
                0x4E,
                0x47,
                0x0D,
                0x0A,
                0x1A,
                0x0A,  # PNG signature
                0x00,
                0x00,
                0x00,
                0x0D,
                0x49,
                0x48,
                0x44,
                0x52,  # IHDR chunk
                0x00,
                0x00,
                0x00,
                0x01,
                0x00,
                0x00,
                0x00,
                0x01,
                0x08,
                0x06,
                0x00,
                0x00,
                0x00,
                0x1F,
                0x15,
                0xC4,
                0x89,
                0x00,
                0x00,
                0x00,
                0x0A,
                0x49,
                0x44,
                0x41,
                0x54,
                0x78,
                0x9C,
                0x63,
                0x00,
                0x01,
                0x00,
                0x00,
                0x05,
                0x00,
                0x01,
                0x0D,
                0x0A,
                0x2D,
                0xB4,
                0x00,
                0x00,
                0x00,
                0x00,
                0x49,
                0x45,
                0x4E,
                0x44,
                0xAE,
                0x42,
                0x60,
                0x82,
            ]
        )
        img = tmp_path / "test.png"
        img.write_bytes(png_data)

        result = image_to_data_url(str(img))
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    def test_valid_jpeg(self, tmp_path: Path) -> None:
        """Valid JPEG file returns data URL with correct MIME type."""
        # Minimal JPEG header
        jpeg_data = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"JFIF" + b"\x00" * 100
        img = tmp_path / "test.jpg"
        img.write_bytes(jpeg_data)

        result = image_to_data_url(str(img))
        assert result is not None
        assert result.startswith("data:image/jpeg;base64,")

    def test_missing_file_returns_none(self) -> None:
        """Non-existent file returns None."""
        result = image_to_data_url("/nonexistent/path/to/image.png")
        assert result is None

    def test_unknown_extension_defaults_to_png(self, tmp_path: Path) -> None:
        """Unknown extension defaults to image/png MIME type."""
        img = tmp_path / "test.unknownext12345"
        img.write_bytes(b"some data")

        result = image_to_data_url(str(img))
        assert result is not None
        assert result.startswith("data:image/png;base64,")

    def test_base64_encoding(self, tmp_path: Path) -> None:
        """Content is correctly base64 encoded."""
        import base64

        content = b"test image data"
        img = tmp_path / "test.png"
        img.write_bytes(content)

        result = image_to_data_url(str(img))
        assert result is not None

        # Extract and decode base64 part
        b64_part = result.split(",")[1]
        decoded = base64.b64decode(b64_part)
        assert decoded == content


class TestProcessImages:
    """Tests for process_images function."""

    def test_without_embedding(self) -> None:
        """Without embedding, returns paths only."""
        paths = ["/path/to/img1.png", "/path/to/img2.jpg"]
        result = process_images(paths, embed=False)

        assert len(result) == 2
        assert result[0] == {"path": "/path/to/img1.png"}
        assert result[1] == {"path": "/path/to/img2.jpg"}

    def test_with_embedding_valid_file(self, tmp_path: Path) -> None:
        """With embedding, includes data_url for valid files."""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake png data")

        result = process_images([str(img)], embed=True)

        assert len(result) == 1
        assert result[0]["path"] == str(img)
        assert "data_url" in result[0]
        assert result[0]["data_url"].startswith("data:")

    def test_with_embedding_missing_file(self) -> None:
        """With embedding, missing files have no data_url."""
        result = process_images(["/nonexistent/image.png"], embed=True)

        assert len(result) == 1
        assert result[0]["path"] == "/nonexistent/image.png"
        assert "data_url" not in result[0]

    def test_empty_paths(self) -> None:
        """Empty paths list returns empty result."""
        result = process_images([], embed=True)
        assert result == []


class TestComputeMetadata:
    """Tests for compute_metadata function."""

    def test_simple_session(self, simple_session: Path) -> None:
        """Metadata is computed correctly for simple session."""
        session = parse_session(simple_session)
        metadata = compute_metadata(session, simple_session)

        assert metadata["session_id"] == "simple"
        assert metadata["total_turns"] == 2
        assert metadata["total_subagents"] == 0
        assert metadata["compactions"] == 0
        assert metadata["started"] == "2026-01-17T10:00:00Z"

    def test_session_with_compaction(self, with_compaction_session: Path) -> None:
        """Compaction count is correct."""
        session = parse_session(with_compaction_session)
        metadata = compute_metadata(session, with_compaction_session)

        assert metadata["compactions"] == 1
        assert metadata["total_turns"] == 2

    def test_empty_session(self, tmp_path: Path) -> None:
        """Empty session has null started timestamp."""
        from cc_flow.models import Session

        session = Session(segments=[], subagents={})
        fake_path = tmp_path / "empty.jsonl"
        metadata = compute_metadata(session, fake_path)

        assert metadata["session_id"] == "empty"
        assert metadata["started"] is None
        assert metadata["total_turns"] == 0


class TestRenderJson:
    """Tests for render_json function."""

    def test_output_is_valid_json(self, simple_session: Path) -> None:
        """Output parses as valid JSON."""
        session = parse_session(simple_session)
        result = render_json(session, simple_session)

        data = json.loads(result)
        assert "metadata" in data
        assert "segments" in data
        assert "subagents" in data

    def test_metadata_first_in_output(self, simple_session: Path) -> None:
        """Metadata key appears first in output."""
        session = parse_session(simple_session)
        result = render_json(session, simple_session)

        # First key should be "metadata"
        assert result.strip().startswith('{\n  "metadata"')

    def test_compact_mode(self, simple_session: Path) -> None:
        """Compact mode produces single-line output."""
        session = parse_session(simple_session)
        result = render_json(session, simple_session, compact=True)

        # Compact JSON has no newlines (except within string values)
        lines = result.strip().split("\n")
        assert len(lines) == 1

    def test_pretty_mode_has_indentation(self, simple_session: Path) -> None:
        """Pretty mode produces indented output."""
        session = parse_session(simple_session)
        result = render_json(session, simple_session, compact=False)

        # Pretty JSON has multiple lines with indentation
        assert "\n  " in result
