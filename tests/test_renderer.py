"""Tests for the renderer module."""

from pathlib import Path

from cc_flow.parser import parse_session
from cc_flow.renderer import json_for_html, render, session_to_dict


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
