# Claude Code Transcript Format

This document describes the JSONL transcript format used by Claude Code to persist conversation history.

---

## 1. Overview

Claude Code stores every conversation as a JSONL (JSON Lines) file — one JSON object per line, appended as the conversation progresses.

### File Locations

```
~/.claude/projects/<project-path-hash>/
├── <session-id>.jsonl              # Main transcript
├── <session-id>/
│   ├── subagents/
│   │   └── agent-<id>.jsonl        # Subagent transcripts
│   └── tool-results/
│       └── <hash>.txt              # Large tool outputs
```

**Project path hash:** The absolute path to the project directory with `/` replaced by `-` and leading `-`.
Example: `/Users/pat/Code/myproject` → `-Users-pat-Code-myproject`

**Session ID:** UUID v4 identifying the conversation session.

### Characteristics

- **Append-only:** Records are only added, never modified or deleted
- **Tree structure:** Records form a tree via `uuid`/`parentUuid`, not a flat list
- **Self-contained:** Each line is valid JSON, parseable independently

---

## 2. Record Structure

Every record shares common fields:

```json
{
  "uuid": "abc123...",
  "parentUuid": "def456...",
  "timestamp": "2026-01-17T12:34:56.789Z",
  "type": "user|assistant|system|progress|file-history-snapshot",
  "subtype": "optional-subtype",
  "message": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `uuid` | string | Unique identifier for this record |
| `parentUuid` | string? | UUID of parent record (null for roots) |
| `timestamp` | string | ISO 8601 timestamp |
| `type` | string | Record type (see below) |
| `subtype` | string? | Optional subtype for system records |
| `message` | object/string | Content varies by type |
| `isCompactSummary` | bool? | True if this is a compaction summary (user records only) |
| `isVisibleInTranscriptOnly` | bool? | True if shown in transcript but not sent to model |

### Record Types

| Type | Purpose |
|------|---------|
| `user` | User input or tool results |
| `assistant` | Model responses |
| `system` | System events (compaction, timing) |
| `progress` | Streaming progress (filter out for analysis) |
| `file-history-snapshot` | File state tracking (filter out for analysis) |

---

## 3. Message Content

### User Messages

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      { "type": "text", "text": "Hello, Claude!" }
    ]
  }
}
```

User content blocks:

| Block Type | Fields | Description |
|------------|--------|-------------|
| `text` | `text` | User's typed message |
| `tool_result` | `tool_use_id`, `content` | Result from tool execution |

**Distinguishing user text from tool results:**
A user record is a "user text" (start of a turn) if the first content block is NOT `tool_result`.

**Note:** Not all `user` records represent actual human input. Some are system-injected messages (see Section 5: System-Injected Messages).

### Assistant Messages

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-5-20251101",
    "id": "msg_01ABC...",
    "role": "assistant",
    "content": [
      { "type": "thinking", "thinking": "Let me consider..." },
      { "type": "text", "text": "Here's my response..." },
      { "type": "tool_use", "id": "toolu_01XYZ", "name": "Bash", "input": {...} }
    ],
    "stop_reason": "end_turn|tool_use|stop_sequence",
    "usage": {
      "input_tokens": 1234,
      "output_tokens": 567,
      "cache_read_input_tokens": 890
    }
  }
}
```

Assistant content blocks:

| Block Type | Fields | Description |
|------------|--------|-------------|
| `thinking` | `thinking`, `signature` | Extended thinking (reasoning) |
| `text` | `text` | Response text |
| `tool_use` | `id`, `name`, `input` | Tool invocation |
| `tool_result` | `tool_use_id`, `content` | (Rare in assistant, usually in user) |

### System Messages

```json
{
  "type": "system",
  "subtype": "compact_boundary",
  "compactMetadata": {
    "trigger": "user|auto",
    "preTokens": 162000,
    "postTokens": 8000
  },
  "message": "compact_boundary"
}
```

System subtypes:

| Subtype | Purpose |
|---------|---------|
| `compact_boundary` | Marks compaction point |
| `turn_duration` | Timing metadata for a turn |

---

## 4. The Conversation Tree

Records form a **tree**, not a flat list. This is fundamental to understanding the format.

### Parent-Child Relationships

```
[Root: user message]
    └── [assistant response]
            └── [user with tool_result]
                    └── [assistant continues]
                            └── [user message]
                                    └── ...
```

Each record points to its parent via `parentUuid`. The conversation flows:
1. User sends message (root or child of previous assistant)
2. Assistant responds (child of user)
3. User record with tool_result (child of assistant's tool_use)
4. Assistant continues (child of tool_result)
5. Repeat

### Finding Roots

A root record has either:
- `parentUuid` is null/undefined
- `parentUuid` references a UUID not present in the dataset

Multiple roots occur when:
- Session starts (first user message)
- After compaction (new segment begins)
- Orphaned records (rare edge case)

---

## 5. System-Injected Messages

Not all `user` records represent actual human input. Claude Code injects system messages that appear as user records but contain automated content. Identifying these is important for accurate visualization and analysis.

### Detection Methods

#### 1. JSONL Metadata Fields (Preferred)

Some system messages include explicit flags:

```json
{
  "type": "user",
  "isCompactSummary": true,
  "message": { ... }
}
```

| Field | Description |
|-------|-------------|
| `isCompactSummary` | True for the summary message after compaction |
| `isVisibleInTranscriptOnly` | True for messages shown in transcript but not sent to model |

#### 2. Content Pattern Detection (Fallback)

When metadata fields aren't present, detect by content prefixes:

| Pattern | Description |
|---------|-------------|
| `This session is being continued` | Compaction summary message |
| `<local-command` | Local CLI command execution |
| `<command-name>` | Skill/command invocation |
| `<command-message>` | Command output |
| `<system-reminder>` | System reminder injection |
| `[Request interrupted` | User interrupted the request |
| `[Image: source:` | Image attachment (screenshot, etc.) |

### Detection Algorithm

```python
def is_system_record(rec: dict) -> bool:
    """Check if a user record is actually system-injected."""
    # Method 1: Check JSONL metadata fields
    if rec.get("isCompactSummary") or rec.get("isVisibleInTranscriptOnly"):
        return True

    # Method 2: Check content patterns
    content = rec.get("message", {}).get("content", [])
    if content and content[0].get("type") == "text":
        text = content[0].get("text", "")
        system_prefixes = [
            "This session is being continued",
            "<local-command",
            "<command-name>",
            "<command-message>",
            "<system-reminder>",
            "[Request interrupted",
            "[Image: source:",
        ]
        return any(text.startswith(prefix) for prefix in system_prefixes)

    return False
```

### Visual Treatment

When visualizing transcripts, system messages are typically styled differently:
- Muted colors (gray/lavender) instead of user colors
- "System" label instead of "Human"
- Helps users distinguish actual input from automated messages

---

## 6. Branches

The tree structure enables **branches** — forks in the conversation.

### What Causes Branching

When a user edits a previous message in the conversation, Claude Code:
1. Keeps the original branch intact
2. Creates a new child from the same parent
3. Continues the conversation on the new branch

### Detecting Branches

A branch point exists when a record has **multiple children** where those children are user text messages.

```
[User: "Write a function"]
    ├── [Assistant: "def foo(): ..."]     ← Original branch
    │       └── [User: "Add error handling"]
    │               └── ...
    │
    └── [Assistant: "def bar(): ..."]     ← User edited, new branch
            └── [User: "Make it async"]
                    └── ...
```

### Branch Detection Algorithm

```python
def find_branches(records):
    children_map = defaultdict(list)
    for r in records:
        if r.get('parentUuid'):
            children_map[r['parentUuid']].append(r)

    branch_points = []
    for parent_uuid, children in children_map.items():
        user_text_children = [c for c in children if is_user_text(c)]
        if len(user_text_children) > 1:
            branch_points.append(parent_uuid)

    return branch_points
```

---

## 7. Segments & Compaction

### What is Compaction?

When context grows too large, Claude Code can **compact** the conversation:
1. Summarize the conversation so far
2. Start fresh with the summary as context
3. Continue from there

The `/compact` command triggers manual compaction. Auto-compaction occurs near context limits.

### Compact Boundary Record

Compaction inserts a `system` record with `subtype: compact_boundary`:

```json
{
  "uuid": "compact-uuid",
  "parentUuid": null,
  "type": "system",
  "subtype": "compact_boundary",
  "timestamp": "2026-01-17T12:00:00Z",
  "compactMetadata": {
    "trigger": "user",
    "preTokens": 162000,
    "postTokens": 8500
  },
  "message": "compact_boundary"
}
```

| Field | Description |
|-------|-------------|
| `trigger` | `"user"` (manual /compact) or `"auto"` |
| `preTokens` | Token count before compaction |
| `postTokens` | Token count after (summary size) |

### Segments

A **segment** is a continuous thread of conversation. A new segment starts:
1. At the beginning of a session (first user message)
2. After a compaction boundary

```
[Segment 0: "Original"]
    User → Assistant → User → ... → (162K tokens)

[compact_boundary] ← preTokens: 162K

[Segment 1: "Continuation"]
    User (summary) → Assistant → User → ...
```

### Post-Compaction Structure

After compaction:
1. `compact_boundary` record becomes a new root
2. First child is a `user` record containing the summary
3. Conversation continues from there

```python
def build_segments(records):
    segments = []

    for root in find_roots(records):
        if root.get('subtype') == 'compact_boundary':
            seg_type = 'continuation'
            compact_meta = root.get('compactMetadata')
            # Find first user_text child as segment start
            start = find_user_text_child(root)
        else:
            seg_type = 'original'
            compact_meta = None
            start = root if is_user_text(root) else find_user_text_child(root)

        turns = collect_turns(start)
        segments.append({
            'type': seg_type,
            'turns': turns,
            'compact_metadata': compact_meta
        })

    return sorted(segments, key=lambda s: s['timestamp'])
```

---

## 8. Session Lifecycle

### Starting a Session

When you start Claude Code in a project:
1. New session ID generated (UUID v4)
2. New JSONL file created
3. Session directory created for subagents/tool-results

### The `/clear` Command

`/clear` **starts a new session**:
- Creates new JSONL file with new session ID
- Old session preserved intact (useful for review)
- Context is completely fresh

**Key difference from `/compact`:**

| Command | Effect | Same Session? |
|---------|--------|---------------|
| `/compact` | Summarizes and continues | Yes |
| `/clear` | Starts fresh | No (new JSONL) |

### Session Continuity

The conversation can be resumed by Claude Code reading the JSONL and reconstructing state. The tree structure preserves:
- Full conversation history
- All branches
- Compaction points and metadata

---

## 9. Subagents

### What are Subagents?

The `Task` tool spawns **subagents** — isolated Claude instances with their own context. Used for:
- Complex multi-step research
- Parallel exploration
- Keeping main context clean

### Subagent Storage

Each subagent gets its own JSONL file:

```
<session-id>/subagents/agent-<agent-id>.jsonl
```

The format is identical to main session transcripts.

### Linking Subagents to Parent

When Task tool completes, the `tool_result` contains the agent ID:

```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01ABC",
  "content": [
    {
      "type": "text",
      "text": "Agent completed successfully.\n\nagentId: 7a8b9c0d1e2f..."
    }
  ]
}
```

Extract with regex: `agentId:\s*([a-f0-9]+)`

### Linking Algorithm

```python
def link_subagents(turns, subagents):
    for turn in turns:
        for item in turn['items']:
            if item['type'] == 'tool_result':
                agent_id = extract_agent_id(item['content'])
                if agent_id:
                    # Find matching tool_use by tool_use_id
                    for prev in turn['items']:
                        if (prev['type'] == 'tool_use' and
                            prev['tool_id'] == item['tool_use_id']):
                            prev['child_agent_id'] = agent_id
                            prev['child_agent'] = subagents.get(agent_id)
```

---

## 10. Special Record Types

### file-history-snapshot

Tracks file state for undo/redo functionality. **Filter out for visualization.**

```json
{
  "type": "file-history-snapshot",
  "message": {
    "files": [
      {"path": "/path/to/file.py", "content": "..."}
    ]
  }
}
```

### progress

Streaming progress updates during tool execution. **Filter out for visualization.**

```json
{
  "type": "progress",
  "message": {
    "type": "tool_execution",
    "tool": "Bash",
    "progress": 0.5
  }
}
```

### system/turn_duration

Timing metadata after each turn completes.

```json
{
  "type": "system",
  "subtype": "turn_duration",
  "message": {
    "duration_ms": 3456
  }
}
```

---

## 11. Parsing Patterns

### Loading Records

```python
def load_records(jsonl_path: Path) -> list[dict]:
    """Load records, filtering out noise."""
    records = []
    with open(jsonl_path) as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                if rec.get('type') not in ('file-history-snapshot', 'progress'):
                    records.append(rec)
    return records
```

### Building the Tree

```python
def build_tree(records: list[dict]) -> tuple[dict, dict]:
    """Build uuid->record map and parent->children map."""
    by_uuid = {r['uuid']: r for r in records if r.get('uuid')}

    children_map = defaultdict(list)
    for r in records:
        parent = r.get('parentUuid')
        if parent and r.get('uuid'):
            children_map[parent].append(r['uuid'])

    # Sort children by timestamp
    for parent, kids in children_map.items():
        kids.sort(key=lambda u: by_uuid.get(u, {}).get('timestamp', ''))

    return by_uuid, children_map
```

### Identifying User Text Messages

```python
def is_user_text(record: dict) -> bool:
    """Check if record is a user text message (not tool_result)."""
    if record.get('type') != 'user':
        return False

    message = record.get('message', {})
    if not isinstance(message, dict):
        return False

    content = message.get('content', [])
    if not content or not isinstance(content, list):
        return False

    first_block = content[0]
    if isinstance(first_block, dict):
        return first_block.get('type') != 'tool_result'

    return True
```

### BFS Traversal for Turns

Breadth-first search correctly handles parallel tool calls:

```python
def collect_turn_items(start_uuid: str, by_uuid: dict, children_map: dict) -> list:
    """Collect all items in a turn using BFS."""
    items = []
    visited = {start_uuid}
    queue = list(children_map.get(start_uuid, []))
    next_user_texts = []

    while queue:
        uuid = queue.pop(0)
        if uuid in visited:
            continue
        visited.add(uuid)

        record = by_uuid.get(uuid)
        if not record:
            continue

        if is_user_text(record):
            next_user_texts.append(uuid)
            continue

        # Extract blocks from this record
        items.extend(extract_blocks(record))

        # Add children to queue
        for child in children_map.get(uuid, []):
            if child not in visited:
                queue.append(child)

    items.sort(key=lambda x: x.get('timestamp', ''))
    return items, next_user_texts
```

### Why BFS?

Linear traversal misses parallel tool calls:

```
[User message]
    └── [Assistant with 3 tool_use blocks]
            ├── [tool_result 1]
            ├── [tool_result 2]  ← Missed by linear traversal!
            └── [tool_result 3]  ← Missed by linear traversal!
                    └── [Assistant continues]
```

BFS visits all siblings before moving deeper, capturing all parallel results.

---

## Appendix A: Example Session

```jsonl
{"uuid":"a1","parentUuid":null,"type":"user","timestamp":"2026-01-17T12:00:00Z","message":{"role":"user","content":[{"type":"text","text":"Hello"}]}}
{"uuid":"a2","parentUuid":"a1","type":"assistant","timestamp":"2026-01-17T12:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"Hi there!"}]}}
{"uuid":"a3","parentUuid":"a2","type":"user","timestamp":"2026-01-17T12:00:05Z","message":{"role":"user","content":[{"type":"text","text":"Run ls"}]}}
{"uuid":"a4","parentUuid":"a3","type":"assistant","timestamp":"2026-01-17T12:00:06Z","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"ls"}}]}}
{"uuid":"a5","parentUuid":"a4","type":"user","timestamp":"2026-01-17T12:00:07Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"file1.txt\nfile2.txt"}]}}
{"uuid":"a6","parentUuid":"a5","type":"assistant","timestamp":"2026-01-17T12:00:08Z","message":{"role":"assistant","content":[{"type":"text","text":"Found 2 files."}]}}
```

Tree visualization:
```
a1 [user: "Hello"]
└── a2 [assistant: "Hi there!"]
    └── a3 [user: "Run ls"]
        └── a4 [assistant: tool_use Bash]
            └── a5 [user: tool_result]
                └── a6 [assistant: "Found 2 files."]
```

---

## Appendix B: Quick Reference

### Record Type Filtering

```python
SKIP_TYPES = {'file-history-snapshot', 'progress'}
useful_records = [r for r in records if r['type'] not in SKIP_TYPES]
```

### Content Block Types

| Location | Block Type | Key Fields |
|----------|------------|------------|
| User | `text` | `text` |
| User | `tool_result` | `tool_use_id`, `content` |
| Assistant | `thinking` | `thinking`, `signature` |
| Assistant | `text` | `text` |
| Assistant | `tool_use` | `id`, `name`, `input` |

### Key Patterns

| Pattern | Detection |
|---------|-----------|
| Turn start | `is_user_text(record)` returns True |
| Branch point | Parent has multiple user_text children |
| Compaction | `type='system'`, `subtype='compact_boundary'` |
| System message | `isCompactSummary` or `isVisibleInTranscriptOnly` field, or content prefix match |
| Subagent spawn | `tool_use` with `name='Task'` |
| Subagent link | `tool_result` content contains `agentId:` |
