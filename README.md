# cc-flow

Visualize Claude Code transcripts as interactive HTML.

## Install

```bash
uv tool install git+https://github.com/papersson/cc-flow
```

## Usage

```bash
# Visualize a session (opens in browser)
cc-flow ~/.claude/projects/<project>/sessions/<session>.jsonl

# Save to specific file
cc-flow session.jsonl -o output.html

# Embed images as base64
cc-flow session.jsonl --embed-images
```

## Features

- Conversation flow with turn-by-turn navigation
- Expandable thinking blocks and tool calls
- Branch visualization for edited messages
- Context compaction boundaries
- Subagent drill-down
- Image attachments
