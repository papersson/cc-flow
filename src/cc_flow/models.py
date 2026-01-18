"""Domain models for cc-flow."""

from enum import Enum

from pydantic import BaseModel


class BlockType(str, Enum):
    """Types of content blocks in assistant responses."""

    THINKING = "thinking"
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class Block(BaseModel):
    """A content block in an assistant response."""

    type: BlockType
    content: str
    timestamp: str | None = None
    tool_name: str | None = None  # for tool_use
    tool_input: str | None = None  # for tool_use (truncated preview)
    tool_use_id: str | None = None  # for tool_result
    child_agent_id: str | None = None  # for tool_use spawning Task
    subagent_type: str | None = None  # for Task tool_use
    full_content: str | None = None  # Full content when truncated
    is_truncated: bool = False


class Turn(BaseModel):
    """A user message + assistant response cycle."""

    id: int  # Local to segment, starts at 0
    user_message: str
    user_timestamp: str
    blocks: list[Block] = []
    parent_turn_id: int | None = None
    children_turn_ids: list[int] = []
    is_branch: bool = False  # True if sibling turns exist
    is_system: bool = False  # True if this is a system-injected message
    image_paths: list[str] = []  # Paths to attached images


class CompactMetadata(BaseModel):
    """Metadata about a compaction event."""

    trigger: str
    pre_tokens: int


class Segment(BaseModel):
    """A continuous thread of conversation."""

    id: int
    type: str  # "original" | "continuation"
    timestamp: str
    turns: list[Turn]
    compact_metadata: CompactMetadata | None = None


class Session(BaseModel):
    """The entire JSONL file representing one conversation."""

    segments: list[Segment]
    subagents: dict[str, list[Turn]]  # agent_id -> turns
