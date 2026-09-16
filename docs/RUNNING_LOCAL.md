# Running CORP locally (laptop + flash drive)

This is the single-machine setup: PostgreSQL and the app run on your laptop, and
the bulk **warm store** lives on an external flash drive. It's the intended
deployment when you don't want CORP consuming a hosted database (e.g. keeping
Railway free for other apps).

```
Laptop ──> PostgreSQL + pgvector (Docker)   ← hot relational data + processed results
      ──> FastAPI app (uvicorn)             ← the API
      ──> React/Vite dashboard              ← the console
Flash  ──> SQLite warm store (warm.db)      ← mirrored bulk (evidence, embeddings, …)
           + raw JSONL archives
```

## Prerequisites

- **Python 3.12+**
- **Docker Desktop** (for Postgres + pgvector — installing pgvector natively on
  Windows is painful, so use the container)
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

## 2. Start PostgreSQL + pgvector

```
docker compose up -d db
```

This runs `pgvector/pgvector:pg16` on `localhost:5432` (user/password/db all
`corp`), with data stored in a Docker volume on your laptop. The pgvector
extension is enabled automatically by the first migration.

## 3. Configure `.env`

Copy the template and edit it:

```
cp .env.example .env
```

Set these for the laptop + flash split (Windows example paths shown — adjust the
drive letter to yours):

```
DATABASE_URL=postgresql+asyncpg://corp:corp@localhost:5432/corp
DATABASE_URL_SYNC=postgresql://corp:corp@localhost:5432/corp
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

API (defaults to port 8000):

```
uvicorn corp.api.app:app --reload
```

Dashboard (defaults to calling `http://localhost:8000`; no config needed):

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
