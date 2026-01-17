"""Property-based tests using Hypothesis."""

import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

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
