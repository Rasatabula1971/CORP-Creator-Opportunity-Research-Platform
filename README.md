# CORP — Creator Opportunity Research Platform

An evidence-first engine for researching creators and their audiences: it
collects public signals, extracts audience problems, clusters them, scores
commercial opportunity, and produces a per-creator dossier for human review.

## Getting started

**→ [docs/RUNNING_LOCAL.md](docs/RUNNING_LOCAL.md)** — run everything on your
laptop (native PostgreSQL + pgvector, the API, the dashboard) with the bulk
warm store on an external flash drive. Start there.

Quick version:

```
pip install -e ".[dev]"
# Install PostgreSQL 16 + the pgvector extension, create the `corp` role/db
cp .env.example .env          # set DATABASE_URL(_SYNC), an LLM key, warm-store path
alembic upgrade head
uvicorn corp.api.app:app --reload --port 8010   # or on Windows: start_corp.bat
cd web && npm install && npm run dev
```

## What's in the box

- **Acquisition adapters** (`corp/workers/adapters/`) — YouTube, Reddit, TikTok,
  creator web presence, plus niche-signal sources: Stack Exchange, search
  demand, Amazon reviews, marketplaces (Gumroad/Etsy/Udemy), Hacker News,
  Wikipedia pageviews, Google Trends, Apple App Store.
- **Multi-source discovery** with a source-health circuit breaker that backs off
  and disconnects tolerated sources that repeatedly fail.
- **Intelligence pipeline** — extraction → clustering → commercial-intent
  classification → opportunity scoring → dossier, driven per creator by the
  `ResearchOrchestrator`.
- **Two-tier storage** — PostgreSQL + pgvector for hot relational data and
  processed results; a SQLite **warm store** (mirrored on external storage) for
  bulk. See RUNNING_LOCAL.md for the hot/warm split and the `prune` command that
  bounds Postgres.
- **API + dashboard** — FastAPI backend (`corp/api/`) and a React/Vite Gate A
  review console (`web/`).

## Architecture & decisions

- Design doc: [`docs/design/CORP_build_design_CIP.md`](docs/design/CORP_build_design_CIP.md)
- Implementation steps: [`docs/design/IMPLEMENTATION_STEPS.md`](docs/design/IMPLEMENTATION_STEPS.md)
- Architecture Decision Records: [`docs/DECISIONS/`](docs/DECISIONS/)

## Development

```
pytest                        # test suite (integration tests need a database)
ruff check corp tests         # lint
mypy corp                     # type check
lint-imports                  # module-boundary contracts
```

Tech stack: Python 3.13+, FastAPI (async), SQLAlchemy 2.0 + asyncpg, PostgreSQL +
pgvector, Pydantic v2, sentence-transformers / HDBSCAN for clustering, React +
Vite + TypeScript for the dashboard.
