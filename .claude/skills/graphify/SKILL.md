---
name: graphify
description: Query the CORP codebase knowledge graph before searching raw files
---

# /graphify — Codebase Knowledge Graph

**graphify** turns the CORP codebase into a queryable knowledge graph with
community detection, god-node identification, and structured audit trails.

## When to use

Before grepping or globbing for codebase structure, check the knowledge graph:

1. Read `graphify-out/GRAPH_REPORT.md` for an overview of god nodes, communities,
   and cross-module connections.
2. Use `graphify query "<question>"` for targeted graph traversal with file:line
   citations.
3. Fall back to grep/glob only when the graph doesn't cover your question.

## Commands

| Command | What it does |
|---------|-------------|
| `graphify .` | Build/rebuild the full knowledge graph |
| `graphify . --update` | Incremental rebuild (changed files only) |
| `graphify query "<question>"` | BFS/DFS traversal, returns subgraph with citations |
| `graphify hook install` | Install git hooks for auto-rebuild on commit |

## Output

All output lives in `graphify-out/`:

- `graph.json` — the persistent queryable graph (NetworkX format)
- `graph.html` — interactive clickable visualization
- `GRAPH_REPORT.md` — plain-language report of communities and key nodes
- `cache/` — extraction cache (avoids redundant processing)

## CORP-specific notes

The CORP codebase has these key structural communities:

- **Core domain models** (`corp/core/models/`) — 13 SQLAlchemy models, Creator as the hub entity
- **Pipeline workers** (`corp/workers/`) — 5 sequential pipelines (acquisition → intelligence → clustering → intent → scoring)
- **Scoring engine** (`corp/core/scoring/`) — YAML-driven weighted scoring with confidence banding
- **State machine** (`corp/core/state/`) — 18-status creator lifecycle with gate transitions
- **API layer** (`corp/api/`) — FastAPI endpoints + dossier HTML generation
- **LLM providers** (`corp/providers/`) — Gemini + FairProvider multi-provider routing

Import boundaries enforced by import-linter: `core` cannot import `workers` or `api`.
