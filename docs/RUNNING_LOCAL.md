# Running CORP locally (laptop + flash drive)

This is the single-machine setup: PostgreSQL and the app run on your laptop, and
the bulk **warm store** lives on an external flash drive. It's the intended
deployment when you don't want CORP consuming a hosted database (e.g. keeping
Railway free for other apps).

```
Laptop ──> PostgreSQL 16 + pgvector (native) ← hot relational data + processed results
      ──> FastAPI app (uvicorn)             ← the API
      ──> React/Vite dashboard              ← the console
Flash  ──> SQLite warm store (warm.db)      ← mirrored bulk (evidence, embeddings, …)
           + raw JSONL archives
```

## Prerequisites

- **Python 3.13+**
- **PostgreSQL 16** installed natively, plus the **pgvector** extension
  (Windows: the EDB installer for Postgres, then the prebuilt pgvector release
  from https://github.com/pgvector/pgvector/releases copied into the Postgres
  `lib/` and `share/extension/` folders)
- **Node.js 18+** (for the dashboard)
- A **flash drive** formatted **exFAT or NTFS** (not FAT32 — FAT32 caps any file
  at 4 GB and `warm.db` will grow past that)
- One **LLM provider key** — Gemini or Groq (the extraction/intent/topics stages
  need it)

## 1. Install dependencies

```
pip install -e ".[dev]"
```

First run of the intelligence pipeline also downloads the `all-MiniLM-L6-v2`
embedding model (~90 MB) via sentence-transformers.

> **Windows note — `hdbscan` and `umap-learn`.** These two clustering
> dependencies compile native/Numba code and often fail to build from source on
> Windows with a plain `pip install`. If the install errors on either one:
>
> - Easiest: create the environment with conda and install them first —
>   `conda install -c conda-forge hdbscan umap-learn` — then run
>   `pip install -e ".[dev]"` for the rest.
> - Or with pip: make sure you're on a recent Python that has prebuilt wheels
>   for both, upgrade the build tooling (`pip install --upgrade pip setuptools wheel`),
>   and if it still tries to compile, install the "Desktop development with C++"
>   workload from the Visual Studio Build Tools.
>
> Everything else (Postgres, migrations, the API, the dashboard) has no native
> build step and installs cleanly.

## 2. Set up PostgreSQL + pgvector

Install PostgreSQL 16 and pgvector natively (see Prerequisites), make sure the
Windows service `postgresql-x64-16` is running, and create the role and
database once as the `postgres` superuser:

```
psql -U postgres -c "CREATE ROLE corp LOGIN PASSWORD 'corp';"
psql -U postgres -c "CREATE DATABASE corp OWNER corp;"
psql -U postgres -d corp -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

The reference setup listens on **port 5433** (`start_corp.bat` checks 5433
first and falls back to 5432). Adjust the port in `.env` if your install uses
the default 5432. Verify with:

```
pg_isready -h localhost -p 5433
```

## 3. Configure `.env`

Copy the template and edit it:

```
cp .env.example .env
```

Set these for the laptop + flash split (Windows example paths shown — adjust the
drive letter to yours):

```
DATABASE_URL=postgresql+asyncpg://corp:corp@localhost:5433/corp
DATABASE_URL_SYNC=postgresql://corp:corp@localhost:5433/corp
WARM_STORE_PATH=D:\CORP DATABASE\warm.db
CORP_DATA_PATH=D:\CORP DATABASE\archives
GEMINI_API_KEY=your-key-here        # or GROQ_API_KEY
# Optional: real subscriber counts + YouTube collection
YOUTUBE_API_KEY=
```

- `DATABASE_URL` (async, app) and `DATABASE_URL_SYNC` (sync, Alembic) point at the
  same local Postgres.
- `WARM_STORE_PATH` / `CORP_DATA_PATH` point at the flash drive.

## 4. Run migrations

```
alembic upgrade head
```

Alembic reads `DATABASE_URL_SYNC` from `.env`, and the first migration enables
pgvector, so this works against a clean database with no extra steps.

## 5. Run the app

API — pass `--port 8010` explicitly. The dashboard calls
`http://localhost:8010` by default, and uvicorn binds its own default of 8000
unless told otherwise, so omitting the flag leaves the console showing
"TypeError: Failed to fetch" against an API that is running perfectly well on
the wrong port:

```
uvicorn corp.api.app:app --reload --port 8010
```

`API_PORT` in `.env` does **not** move a manually launched server: nothing in
the app reads it, because uvicorn's CLI is what binds the socket. It is read by
`start_corp.bat`, which passes it through as `--port`. To use a different port,
change both the `--port` flag and the dashboard's API base URL (Settings → API
base URL, or `web/src/api/client.ts`).

On Windows, `start_corp.bat` does steps 2, 4 and 5 in one go: it checks
Postgres, applies migrations, reads `API_PORT` from `.env` (default 8010),
refuses to start if that port is already taken, launches uvicorn and the
dashboard in their own windows, and then **starts one autonomous discovery
pass** (`scripts/start_discovery.ps1`: `POST /discovery/run`, followed to the
end in the launcher window with a per-topic and per-stage summary). That is
the frozen flow running unattended: the LLM picks the topics, drills them
into niches, and the chain runs through to dossiers at the human gate. Set
`AUTO_DISCOVERY=false` in `.env` to launch without a pass. The pass needs an
LLM key (`GEMINI_API_KEY` or `GROQ_API_KEY`); without one the script says so
and exits, and the API and dashboard keep running.

### FAIR (the LLM router)

CORP's LLM calls go through FAIR, installed as an editable package from its own
clone (`pip install -e <path to FAIR-Free-AI-Router>`; branch `main`). Pulling
that clone updates it; no reinstall. Three things in CORP's `.env` matter:

- `FAIR_CONFIRMED_FREE_PROVIDERS` — FAIR routes to a recurring free-tier
  provider (Gemini, Groq, Mistral, Z.ai, Cloudflare Workers AI) only when you
  attest the account is free-only and cannot auto-bill. Comma-separated FAIR
  provider ids, e.g. `google_gemini_api,groq,mistral,zai_free,cloudflare_workers_ai`.
  A keyed provider missing here is skipped, and `GET /providers/health` says so
  under `skipped`. OpenRouter Free and Kilo Free need no confirmation.
- `FAIR_ENV_FILE=fair.env` — the keys for FAIR's other providers (see
  `fair.env.example`).
- `FAIR_MAX_UNANSWERED_ATTEMPTS` (default 6) — models that never answered
  tolerated per solve before FAIR escalates.
- `FAIR_REQUIRED` (default `false`) — when `true`, `LLM_PROVIDER=auto` will not
  fall back to the raw Gemini/Groq pool if FAIR is unusable. The raw pool
  bypasses FAIR's free-only check, so with this set an LLM call fails closed
  rather than risk a charge on a key attached to a billable account. Leave it
  `false` to keep the pool fallback.

`GET /providers/health` runs one probe solve and reports each provider's
governor status (`ACTIVE`, `THROTTLED`, `OUTAGE`, `QUOTA_EXHAUSTED`) plus the
skipped ones with FAIR's reason; `start_corp.bat` prints the same before it
starts a discovery pass. FAIR's routing events (a failed attempt with its
cause, an escalation with its reason) are logged at warning level in the API
window.

Dashboard (defaults to calling `http://localhost:8010`; override it in
Settings → API base URL if you moved the API):

```
cd web
npm install
npm run dev
```

## How the hot/warm split actually works

The pipeline **dual-writes**: bulk rows (evidence, problem observations,
content, interactions, metrics) are written to **both** Postgres and the warm
store, and the dashboard reads only from Postgres. So:

- **Postgres** holds everything the app reads — hot relational data *and* the
  processed bulk (evidence text, embeddings, clusters, scores).
- **The flash warm store** is a mirror of the bulk: a portable archive/backup,
  not a way to keep Postgres small on its own.

### Keeping Postgres bounded

Metric-history snapshots grow with every collection run. Prune the old ones
(the warm store keeps the full record):

```
python -m corp.workers.run prune                    # dry-run: shows what would go
python -m corp.workers.run prune --apply            # delete history older than 90 days
python -m corp.workers.run prune --retention-days 30 --apply
```

Only `metrics_snapshots` is pruned — it's append-only history whose latest values
are already denormalized onto the content/account rows, nothing references it, and
the API doesn't read it. Evidence and observations are **not** pruned: the
dashboard reads them and clusters/scores reference them, so removing them would
delete research results. For creator-research volumes on a laptop disk, this is
the right trade — the evidence/embedding data stays put and stays queryable.

## Flash-drive notes

- **Keep the drive plugged in during pipeline runs.** If it's missing, warm-store
  writes are skipped with a warning (they don't crash the run, and they don't get
  written to your C: drive). The dashboard still works — it reads from Postgres.
- **Format exFAT or NTFS.** FAT32's 4 GB file cap will eventually break `warm.db`.
- **Eject properly.** SQLite on removable media can corrupt if the drive is pulled
  mid-write.

## Warm store utilities

```
python -m corp.workers.run warm-init          # create the SQLite schema on the flash drive
python -m corp.workers.run warm-status        # row counts + path
python -m corp.workers.run warm-export DIR    # export warm tables to JSONL
```

## Common commands

```
python -m corp.workers.run add-campaign "My campaign"
python -m corp.workers.run add-creator "Name" youtube @handle
python -m corp.workers.run research <creator_id>
python -m corp.workers.run discover <campaign_id> <source> "<query>"
```
