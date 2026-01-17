"""Pytest configuration and fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory path."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_session(fixtures_dir: Path) -> Path:
    """Return path to simple.jsonl fixture."""
    return fixtures_dir / "simple.jsonl"


@pytest.fixture
def with_branches_session(fixtures_dir: Path) -> Path:
    """Return path to with_branches.jsonl fixture."""
    return fixtures_dir / "with_branches.jsonl"


@pytest.fixture
def with_compaction_session(fixtures_dir: Path) -> Path:
    """Return path to with_compaction.jsonl fixture."""
    return fixtures_dir / "with_compaction.jsonl"


@pytest.fixture
def with_subagent_session(fixtures_dir: Path) -> Path:
    """Return path to with_subagent.jsonl fixture."""
    return fixtures_dir / "with_subagent.jsonl"
