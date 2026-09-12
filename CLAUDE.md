# CORP — Creator Opportunity Research Platform

## graphify

A knowledge graph of this codebase lives in `graphify-out/`. Before answering
architecture or structural questions, read `graphify-out/GRAPH_REPORT.md` for
god nodes and community structure. Use `graphify query "<question>"` for
targeted graph traversal instead of grepping raw files.

After making code changes, rebuild incrementally: `graphify . --update`

### Setup

```bash
uv tool install graphifyy    # or: pipx install graphifyy
graphify .                    # build the initial knowledge graph
graphify hook install         # auto-rebuild on git commit
```
