# OKF MCP Server

MCP (Model Context Protocol) server for OKF vaults. Exposes 17 tools that let AI agents (Claude Code, Hermes, Cursor, etc.) query, create, and analyze concepts in a knowledge vault — no direct filesystem access needed.

## What is OKF?

OKF (Open Knowledge Format) is a convention for representing knowledge as markdown files with YAML frontmatter. The minimum contract is:

```markdown
---
type: Decision
title: "My first decision"
description: "One-line summary explaining what this concept is"
---

Free-form markdown content. Use [[wikilinks]] to
connect concepts together.
```

Each `.md` file is a **concept**. Concepts link to each other with `[[wikilinks]]`, forming a navigable knowledge graph. The OKF MCP exposes that graph as semantic tools for AI agents.

## Quick Start

### 1. Prerequisites

- Python 3.12+
- `mcp` (FastMCP)

```bash
pip install mcp
```

### 2. Installation

```bash
git clone https://github.com/Jabar42/mcp-okf.git
cd mcp-okf
pip install .
```

This installs the `okf-mcp` command in your PATH.

### 3. Configure your vault

Copy the example config to your vault root and edit it:

```bash
cp okf.config.example.yaml ~/my-vault/.okf.config.yaml
```

Edit the sections you need — at minimum, change `health.smoke_entry_point` to a concept that exists in your vault. All keys are optional; if something is missing, defaults are used.

Config resolution order:
1. `--config <path>` in the CLI
2. `$OKF_CONFIG` environment variable
3. `<vault>/.okf.config.yaml` (next to your `.md` files)
4. `~/.config/okf/config.yaml` (global)
5. Embedded defaults

Vault resolution order:
1. `--vault <path>` in the CLI
2. `$OKF_VAULT` environment variable
3. `~/OKF-Vault` (default)

### 4. Run the health check

```bash
python3 -m cli health --vault ~/my-vault
```

If you see `Health: 9/9`, your vault is ready.

### 5. Register the MCP with your agent

**Claude Code** (`~/.claude/.mcp.json`):

```json
{
  "mcpServers": {
    "okf": {
      "command": "okf-mcp",
      "args": []
    }
  }
}
```

**Hermes Agent** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  okf:
    command: okf-mcp
    args: []
```

**Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "okf": {
      "command": "okf-mcp",
      "args": []
    }
  }
}
```

> If using `python3 server.py` instead of `okf-mcp`, the path in `args` MUST be absolute. MCP clients do not resolve relative paths in `args`, even with the `cwd` field.

## Available Tools

| Tool | Description |
|---|---|
| `okf_traverse` | Semantic graph traversal — **primary query tool** |
| `okf_read` | Read a concept's full body |
| `okf_search` | FTS5 search — **fallback**, prefer traverse |
| `okf_graph` | Graph analysis: orphans, hubs, backlinks, clusters |
| `okf_new` | Create a new concept with validated OKF frontmatter |
| `okf_health` | Vault health check (9 checks) |
| `okf_index` | Regenerate index.md and log.md |
| `okf_touch` | Read statistics |
| `okf_review` | Concepts with past-due review_on (cybernetic loop) |
| `okf_stale` | Semantic staleness detector |
| `okf_session_metrics` | Aggregated session metrics |
| `okf_analytics` | Analytics queries over trace events |
| `okf_graph_command` | Commands to the Cognitive Trace plugin in Obsidian |
| `okf_graph_suggest_edge_types` | Suggest typed edge types for wikilinks |
| `okf_graph_impact` | Ontological impact analysis |
| `okf_file_info` | Concept file metadata (created/updated dates) |
| `okf_trace` | Reference trace across all ecosystem layers |

## The Semantic Graph

The primary tool is `okf_traverse`. Unlike keyword search, traversal follows the graph's wikilinks:

```
okf_traverse("my-concept", depth=2)
→ concept frontmatter
→ outgoing linked concepts (wikilinks)
→ incoming linked concepts (backlinks)
→ corrected concepts (cyber.corrects)
→ typed edges: extends, refines, grounds, applies, depends, corrects
```

This lets the agent **reason about knowledge structure**, not just match text.

## Concept Types

Types are predefined in the configuration file:

| Type | Purpose | Has cyber |
|---|---|---|
| `Decision` | Architectural or policy decision | Yes |
| `Plan` | Execution plan or roadmap | Yes |
| `Project` | Project with vision, status, and components | Yes |
| `Insight` | Observation, pattern detected, implication | Yes |
| `Framework` | Conceptual framework | No |
| `Lesson` | Lesson from experience | No |
| `Tool` | Tool or script | No |
| `Spec` | Technical specification | No |
| `System` | Ecosystem runtime configuration | Yes |
| `Agent` | AI agent definition | Yes |
| `Skill` | Hermes skill catalog | No |
| `Workflow` | Procedure or workflow | No |
| `Criterion` | Decision rule or criterion | No |
| `Session` | Session summary | No |
| `Research` | Research or paper | No |

The `cyber` block (sensor → target_metric → review_on) is optional and only applies to types marked with Yes.

## Typed Edges

Concepts can declare edges with explicit semantics in the `links:` frontmatter field:

| Type | Meaning |
|---|---|
| `extends` | A adds a dimension to B |
| `refines` | A narrows or clarifies B |
| `grounds` | A is the theoretical basis for B |
| `applies` | A implements B |
| `depends` | A requires B to exist |
| `corrects` | A replaces/invalidates part of B (only if B is deprecated) |

## Advanced Configuration

### Cybernetic Loop

If you use the `cyber` block in your concepts, the MCP can close the loop automatically:

1. `okf_new --cyber` assigns `review_on: +14d`
2. `okf_review` lists concepts with past-due reviews
3. An autonomous agent evaluates the outcome (success/failure) and updates

### Staleness Detection

`okf_stale` evaluates 7 semantic staleness signals:
1. Old timestamp (>90 days without meaningful changes)
2. Few reads (<2 in 90 days)
3. Ghost proposal (>30 days in "proposed" status)
4. Orphan (no incoming or outgoing wikilinks)
5. No commits (>180 days without commits touching the file)
6. Decision without status
7. Outdated description (checkboxes complete but description still references problems)

Adjust thresholds in `stale.*` of your `.okf.config.yaml`.

## Development

```bash
# Run tests
cd tests && python3 test_server.py

# Test the server manually (JSON-RPC stdio)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python3 server.py
```

## License

MIT

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed, date-versioned list of added features, fixes, and changes.
