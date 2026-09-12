# CORP Implementation Steps — Coding Roadmap

**Derived from:** CORP_build_design_CIP.md v1.1 + corp_cip_project.yaml
**Created:** 2026-09-12
**Branch:** claude/determined-volta-q5xa17

---

## Phasing Strategy

The build follows the CIP discipline: **migration → core domain → worker → pytest against real Postgres → bug-injection pass**. Each step is a commit-sized unit that can be tested independently.

The thin-slice target is: **YouTube → collect → extract → cluster → intent → one dossier → Gate A** for a single creator.

---

## Step 0 — Project Scaffold (Adopt CIP)

**Goal:** Reproducible dev environment + enforced architectural boundaries.

### 0.1 Python project setup
- `pyproject.toml` with:
  - Python 3.12+
  - import-linter contracts: `core/` never imports `workers/`
  - `PYTHONHASHSEED=random` in test config
  - Dependencies: `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `alembic`, `pydantic`, `pydantic-settings`, `asyncpg`
- `.python-version` → 3.12
- `uv` or `pip-tools` for dependency management

### 0.2 Database scaffold
- `docker-compose.yml` — Postgres 16 + pgvector extension
- Alembic init with async driver config
- Base SQLAlchemy model with `created_at`, `updated_at` mixins

### 0.3 Directory structure
```
corp/
  core/           # pure domain — NEVER imports workers/
    models/
    scoring/
    evidence/
    rules/
    intent/
    state/
  workers/
    adapters/
    acquisition/
    intelligence/
    research/
    providers/
    dossier/
  api/
  web/            # React + Vite (later)
migrations/
rules/            # YAML scoring weights, eligibility, intent
tests/
  core/
  workers/
  api/
  integration/
```

### 0.4 Config
- `pydantic-settings` config class: DB URL, YouTube API key, Gemini API key, rate limit params
- `.env.example` template

### 0.5 CI/test harness
- `pytest.ini` / pyproject.toml test section
- Fixture for test Postgres (testcontainers or docker-compose)
- `conftest.py` with DB session fixture

**Deliverable:** `pytest` runs green on an empty test suite against real Postgres 16.

---

## Step 1 — Core Data Model (Adapt CIP Evidence Model)

**Goal:** The relational spine — all entities the pipeline writes to.

### 1.1 Core entities (SQLAlchemy models + Pydantic schemas)

| Entity | Key fields | Notes |
|--------|-----------|-------|
| `Creator` | id, name, niche, discovery_source, status (state machine) | Top-level |
| `CreatorPlatformAccount` | creator_id FK, platform, handle, external_id, verified | One creator → many platforms |
| `ContentItem` | id, creator_id FK, platform, external_id, title, published_at, content_type | Videos, posts |
| `AudienceInteraction` | id, content_item_id FK, external_id, text, author_handle, interaction_type, posted_at | Comments, replies |
| `Evidence` | id, source_type, source_id, raw_text, collected_at, access_method, compliance_status | Append-only provenance |
| `ProblemObservation` | id, evidence_id FK, text, category, is_inferred, extraction_prompt_version, model_version | One comment → many observations |
| `ProblemCluster` | id, label, description, frequency, recency_score, evidence_strength | Cross-creator capable (PDR #3) |
| `ProblemClusterMember` | cluster_id FK, observation_id FK, similarity_score | Many-to-many |
| `CommercialSignal` | id, problem_cluster_id FK, signal_level, evidence_id FK, classification_model | weak/moderate/strong/validation |
| `CreatorScore` | id, creator_id FK, component_scores (JSON), aggregate_score, computed_hash, rule_version, model_version | Deterministic (PDR #6) |
| `OpportunityScore` | id, creator_id FK, problem_cluster_id FK, component_scores, aggregate_score, computed_hash | Split from CreatorScore (PDR #6) |
| `HumanDecision` | id, creator_id FK, opportunity_id FK, decision (approve/reject/watch), rationale, decided_at, gate | Gate A–E |
| `ResearchRun` | id, creator_id FK, started_at, completed_at, status, config_snapshot (JSON) | Audit trail |

### 1.2 Alembic migration
- Initial migration creating all tables
- pgvector extension enable
- Embedding column on `ProblemObservation` (vector(384) for all-MiniLM)

### 1.3 Tests
- Model creation + relationship traversal
- Evidence append-only constraint (no UPDATE/DELETE policy or trigger)
- `computed_hash` determinism test

**Deliverable:** Migration runs clean; models round-trip through DB; evidence is append-only.

---

## Step 2 — YouTube Adapter (Wrap google-api-python-client)

**Goal:** Given a channel handle → videos → comments → captions, emitted in the normalized schema.

### 2.1 Normalized adapter interface (`workers/adapters/base.py`)
- Abstract `SourceAdapter` protocol
- `NormalizedContent` pydantic model — the one schema both adapter families emit
  - Fields: `source_platform`, `content_type`, `external_id`, `text`, `author`, `timestamp`, `parent_id`, `access_method`, `compliance_status`
- This is the **Build** item from the capability decomposition

### 2.2 YouTube adapter (`workers/adapters/youtube.py`)
- `resolve_channel(handle) → channel_id` via YouTube Data API v3
- `list_videos(channel_id, max_results, published_after) → list[ContentItem]`
- `get_comment_threads(video_id) → list[AudienceInteraction]`
- `get_captions(video_id) → str` via `youtube-transcript-api`
- Rate limiting: `pyrate-limiter` (10k units/day budget tracking)
- Retry: `tenacity` with exponential backoff
- All outputs → `NormalizedContent` schema

### 2.3 Acquisition orchestrator (`workers/acquisition/collector.py`)
- `collect_creator_data(channel_handle) → ResearchRun`
- Stores `ContentItem` + `AudienceInteraction` + `Evidence` rows
- Each stored item gets an `Evidence` row with provenance

### 2.4 Tests
- Unit tests with mocked API responses (cassettes or fixtures)
- Integration test: real API call against a known public channel (gated by env var)
- Rate limit tracking test
- Normalized schema validation

**Deliverable:** `collect_creator_data("@mkbhd")` stores videos + comments + evidence in DB.

---

## Step 3 — Content + Audience Intelligence (Wrap Gemini)

**Goal:** LLM extraction — topic classification + per-comment problem/question/pain extraction.

### 3.1 Provider routing (`workers/providers/registry.py`)
- Adapt CIP's deterministic provider routing
- Provider registry: Gemini free tier as primary
- Deterministic call logging (model + prompt version + response hash)

### 3.2 Topic classification (`workers/intelligence/topics.py`)
- Gemini structured output → creator's content topics
- Pydantic response model: `TopicClassification(topics: list[Topic])`
- Store per `ContentItem`

### 3.3 Problem extraction (`workers/intelligence/extraction.py`)
- Per-comment extraction: problem / question / pain / request
- Gemini + `instructor` or raw structured output
- Output: `ProblemObservation` rows, each FK'd to `Evidence`
- Enforce observed-vs-inferred distinction (§8): `is_inferred` flag
- **Pin prompt version per ResearchRun** (PDR #9)

### 3.4 Tests
- Extraction against fixture comments → known ProblemObservations
- Observed-vs-inferred enforcement
- Prompt version pinning
- Evidence FK chain: Comment → Evidence → ProblemObservation

**Deliverable:** Comments → structured ProblemObservations with full evidence chain.

---

## Step 4 — Problem Clustering (Adopt BERTopic / HDBSCAN)

**Goal:** Embed observations → cluster → label problem families.

### 4.1 Embeddings (`workers/intelligence/embeddings.py`)
- `sentence-transformers` with `all-MiniLM-L6-v2` (local, free)
- Embed `ProblemObservation.text` → vector(384)
- Store in pgvector column
- Batch processing for efficiency

### 4.2 Clustering (`workers/intelligence/clustering.py`)
- BERTopic pipeline: embed → UMAP → HDBSCAN → c-TF-IDF → labels
- Pin model versions for determinism
- Output: `ProblemCluster` with `ProblemClusterMember` links
- Frequency + recency scoring per cluster
- **Cross-creator capable** (PDR #3): cluster spans creators when run across multiple

### 4.3 Tests
- Determinism: same input → same clusters (pinned UMAP seed)
- Cluster quality: fixture set with known groupings
- Cross-creator aggregation test

**Deliverable:** ProblemObservations grouped into labeled clusters with frequency/recency metrics.

---

## Step 5 — Commercial Intent (Build rules table + Wrap Gemini)

**Goal:** Classify clusters by purchase intent level.

### 5.1 Intent rules table (`core/intent/hierarchy.py` + `rules/intent.yaml`)
- Signal hierarchy: weak / moderate / strong / validation
- YAML-driven rules (not hardcoded)
- Example signals per level:
  - Weak: general complaint, vague wish
  - Moderate: specific problem description, comparison seeking
  - Strong: "where can I buy", pricing questions, product requests
  - Validation: already paying for alternatives, reviewing competitors

### 5.2 Intent classifier (`workers/intelligence/intent.py`)
- Gemini classifier over the signal hierarchy
- Input: `ProblemCluster` + representative evidence
- Output: `CommercialSignal` FK'd to `Evidence`
- Deterministic logging

### 5.3 Tests
- Rules table loading + validation
- Classification against known-intent fixtures
- Signal hierarchy ordering

**Deliverable:** Each ProblemCluster has a CommercialSignal with evidence-backed intent level.

---

## Step 6 — Scoring + Confidence (Adapt CIP Steps 9 + 12)

**Goal:** Deterministic, reproducible component + aggregate scores with YAML-driven weights.

### 6.1 YAML decision rules (`rules/scoring.yaml`)
- Weight dimensions from CORP §7:
  - Audience problem frequency
  - Recency / trend (PDR #7)
  - Commercial intent strength
  - Evidence depth (number of independent sources)
  - Creator reach (subscriber count, engagement rate)
  - Competition saturation
- Confidence banding thresholds

### 6.2 Scoring engine (`core/scoring/engine.py`)
- Component score calculation per dimension
- Aggregate score with YAML weights
- `computed_hash` for reproducibility (Adapt CIP Step 9)
- `CreatorScore` + `OpportunityScore` (split per PDR #6)
- Rule version + model version stored per score

### 6.3 Confidence banding (`core/scoring/confidence.py`)
- Adapt CIP EOR banding pattern
- Bands: High / Medium / Low / Insufficient
- Factors: source count, evidence depth, data freshness, single-source penalty

### 6.4 Tests
- Determinism: same input → same score → same hash
- Weight reconfiguration via YAML change
- Confidence banding thresholds
- Score reproducibility from stored components

**Deliverable:** Creator + Opportunity scores, deterministic and reproducible, with confidence bands.

---

## Step 7 — Dossier Generation (Wrap Jinja2 + Build template)

**Goal:** The §13 decision-ready dossier for one creator.

### 7.1 Dossier template (`workers/dossier/templates/dossier.html.j2`)
- CORP §13 structure:
  - Creator overview (name, niche, reach metrics)
  - Top audience problems (clustered, ranked by opportunity score)
  - Evidence drill-down per problem (actual quotes, sources)
  - Commercial intent assessment
  - Competitive landscape (Phase 5+ — stub for now)
  - Recommended product concepts (Phase 5+ — stub for now)
  - Confidence assessment + data coverage
  - Score breakdown (component + aggregate)

### 7.2 Dossier engine (`workers/dossier/generator.py`)
- Load creator + all related data
- Render via Jinja2
- Output: HTML (primary), with optional Markdown export

### 7.3 Tests
- Render against fixture data → valid HTML
- All evidence references resolve
- Score breakdown matches stored scores

**Deliverable:** Full dossier for one creator, with evidence drill-down and score transparency.

---

## Step 8 — Minimal Console + Gate A (Mirror CIP Step 14)

**Goal:** Human review interface — see dossier, drill into evidence, approve/reject/watch.

### 8.1 FastAPI read/write API (`api/`)
- `GET /creators` — list with status/score filters
- `GET /creators/{id}` — full detail
- `GET /creators/{id}/dossier` — rendered dossier
- `GET /creators/{id}/evidence` — evidence chain
- `GET /creators/{id}/opportunities` — scored opportunities
- `POST /creators/{id}/decisions` — record HumanDecision (Gate A)
- `GET /research-runs` — audit trail

### 8.2 Gate A logic (`core/state/gates.py`)
- State machine transition: research_complete → human_review → approved/rejected/watching
- `HumanDecision` recorded with rationale
- Append-only override pattern from CIP Steps 10–11

### 8.3 React console (`web/`)
- Vite + React + shadcn/ui + TanStack Table
- Creator list with sorting/filtering
- Dossier view with evidence drill-down
- Decision buttons (Approve / Reject / Watch)
- Research run history

### 8.4 Tests
- API endpoint tests
- Gate A state transitions
- Decision recording + audit trail

**Deliverable:** Working console where a human reviews one dossier and records a decision.

---

## Implementation Order & Dependencies

```
Step 0 (scaffold) ──→ Step 1 (data model) ──→ Step 2 (YouTube adapter)
                                                    │
                                              Step 3 (intelligence)
                                                    │
                                              Step 4 (clustering)
                                                    │
                                              Step 5 (intent)
                                                    │
                                              Step 6 (scoring)
                                                    │
                                              Step 7 (dossier)
                                                    │
                                              Step 8 (console + Gate A)
```

Steps are strictly sequential — each depends on the prior step's models/infrastructure.

---

## Key Architectural Decisions (Pre-resolved)

1. **core/ ⊥ workers/**: Enforced by import-linter. Core contains models, scoring, evidence, rules, state. Workers contain adapters, intelligence, acquisition, providers, dossier.
2. **Evidence is append-only**: No UPDATE/DELETE on the Evidence table. Ever.
3. **LLM output is never a source**: LLM extractions reference evidence; they are not evidence themselves.
4. **Deterministic scoring**: Same inputs + same rules → same score → same hash. Verified by test.
5. **Free-tier-first**: Gemini free tier, local embeddings, Postgres. Paid APIs only for vendor scrape adapters (post-v1).
6. **Prompt version pinning**: Every LLM call logs prompt version + model version on the ResearchRun.
7. **Split CreatorScore / OpportunityScore**: A small creator with a great problem outranks a big creator with none.

---

## Deferred (Only If Thin Slice Earns It)

- Discovery/eligibility automation (Phase 2)
- Identity resolution across platforms
- Deep-research second pass (Phases 7/12)
- Feedback-loop weight recalibration (Phase 8)
- Cross-niche discovery (Phase 9)
- IG/TikTok/Reddit/FB vendor-scrape adapters
- Niche-signal adapters (search demand, Amazon reviews, Stack Exchange)
- Cost & throughput budget enforcement
- Evaluation harness / ground-truth seed (PDR #2)
- Disqualifiers ruleset (PDR #8)
- Calibration governance (PDR #10)
