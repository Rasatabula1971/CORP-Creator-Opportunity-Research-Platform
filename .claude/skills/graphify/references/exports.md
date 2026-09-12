# Graphify Export Reference

## Standard exports (automatic)

- `graphify-out/graph.json` — NetworkX JSON graph
- `graphify-out/graph.html` — interactive browser visualization
- `graphify-out/GRAPH_REPORT.md` — community report

## Optional exports

| Flag | Output | Notes |
|------|--------|-------|
| `--neo4j` | Cypher files | MERGE-based, safe to re-run |
| `--neo4j-push` | Direct push | `bolt://localhost:7687`, user `neo4j` |
| `--falkordb` | OpenCypher | For FalkorDB graph DB |
| `--falkordb-push` | Direct push | `falkordb://localhost:6379` |
| `--svg` | SVG diagram | Visual export |
| `--graphml` | GraphML file | Structured format |
| `--wiki` | Wiki docs | Generated before cleanup |
| `--obsidian` | Obsidian vault | Linked markdown notes |

## MCP server

`graphify . --mcp` launches a stdio MCP server exposing:
- `query_graph` — natural language graph traversal
- `get_node` — single node details
- `get_neighbors` — adjacent nodes
- `graph_stats` — graph-level metrics
