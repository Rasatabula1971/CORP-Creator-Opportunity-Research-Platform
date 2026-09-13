# Graph Report - CORP-Creator-Opportunity-Research-Platform  (2026-09-13)

## Corpus Check
- 115 files · ~40,508 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 4, .example 1, .ini 1)

## Summary
- 971 nodes · 2584 edges · 71 communities (35 shown, 8 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 363 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d8c58d97`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- routes.py
- CreatorStatus
- test_scoring_engine.py
- CORP Implementation Steps — Coding Roadmap
- test_fair_provider.py
- ConfidenceBand
- ClusterPipeline
- test_endpoints.py
- test_models_db.py
- test_intelligence_pipeline.py
- YouTubeAdapter
- test_intent_pipeline.py
- SignalLevel
- What You Must Do When Invoked
- test_extraction.py
- AccessMethod
- test_dossier_generator.py
- LLMProvider
- CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1
- test_youtube_adapter.py
- .list_videos
- test_topics.py
- test_collector.py
- embed_texts
- clean_db
- NormalizedContent
- test_generate_json_with_system_prompt
- load_yaml_rules
- graphify reference: extra exports and benchmark
- CORP Search-Before-Build Checklist
- test_migration.py
- graphify reference: query, path, explain
- schemas/intelligence.py
- _RateLimiter
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- CORP — Creator Opportunity Research Platform
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- .claude/CLAUDE.md
- extraction-spec.md
- corp

## God Nodes (most connected - your core abstractions)
1. `Creator` - 48 edges
2. `SignalLevel` - 48 edges
3. `CreatorStatus` - 44 edges
4. `ResearchRun` - 42 edges
5. `AccessMethod` - 41 edges
6. `Evidence` - 41 edges
7. `LLMProvider` - 41 edges
8. `ComplianceStatus` - 40 edges
9. `ProblemObservation` - 40 edges
10. `DossierGenerator` - 37 edges

## Surprising Connections (you probably didn't know these)
- `FakeSignal` --uses--> `SignalLevel`  [INFERRED]
  tests/workers/test_dossier_generator.py → corp/core/models/intent.py
- `_seed()` --uses--> `CompetitorType`  [INFERRED]
  tests/api/test_endpoints.py → corp/core/models/competitive.py
- `FakeCompetitor` --uses--> `CompetitorType`  [INFERRED]
  tests/workers/test_dossier_generator.py → corp/core/models/competitive.py
- `_seed()` --uses--> `CompetitorStrength`  [INFERRED]
  tests/api/test_endpoints.py → corp/core/models/competitive.py
- `_seed_full()` --uses--> `CompetitorStrength`  [INFERRED]
  tests/integration/test_dossier_pipeline.py → corp/core/models/competitive.py

## Import Cycles
- None detected.

## Communities (71 total, 8 thin omitted)

### Community 0 - "routes.py"
Cohesion: 0.08
Nodes (73): create_decision(), get_competitors(), get_creator(), get_dossier(), get_evidence(), get_opportunities(), list_creators(), list_research_runs() (+65 more)

### Community 1 - "CreatorStatus"
Cohesion: 0.14
Nodes (31): CreatorStatus, str, DecisionType, Gate, str, DecisionCreate, DecisionResponse, BaseModel (+23 more)

### Community 2 - "test_scoring_engine.py"
Cohesion: 0.06
Nodes (56): CompetitorStrength, compute_hash(), compute_score(), get_score_band(), load_scoring_rules(), Any, Higher = more whitespace (less saturated), matching the "higher is better"…, Deterministic hash: same inputs → same hash. Adapted from CIP Step 9. (+48 more)

### Community 3 - "CORP Implementation Steps — Coding Roadmap"
Cohesion: 0.04
Nodes (47): 0.1 Python project setup, 0.2 Database scaffold, 0.3 Directory structure, 0.4 Config, 0.5 CI/test harness, 1.1 Core entities (SQLAlchemy models + Pydantic schemas), 1.2 Alembic migration, 1.3 Tests (+39 more)

### Community 4 - "test_fair_provider.py"
Cohesion: 0.10
Nodes (29): FairProvider, FairProviderError, AsyncClient, Exception, FAIR Free AI Router provider — governed multi-provider LLM backend., FAIR routing failed and no output was returned., LLM provider backed by a FAIR Free AI Router instance. Sends prompts to FAIR's…, accepted_provider() (+21 more)

### Community 5 - "ConfidenceBand"
Cohesion: 0.26
Nodes (14): ConfidenceBand, str, OpportunityScoreResponse, BaseModel, ScoreResponse, compute_confidence_band(), Confidence banding driven by YAML thresholds when provided. Args: thresholds:…, test_custom_thresholds_override_defaults() (+6 more)

### Community 6 - "ClusterPipeline"
Cohesion: 0.08
Nodes (50): ClusterPipeline, AsyncSession, datetime, ndarray, Embeds ProblemObservations, clusters them, and persists results., Run clustering pipeline. Args: creator_id: Scope to a single creator, or None…, _build_clusters(), cluster_observations() (+42 more)

### Community 7 - "test_endpoints.py"
Cohesion: 0.18
Nodes (28): BaseSettings, create_app(), _get_cors_origins(), FastAPI application factory., Settings, get_session(), AsyncSession, FastAPI (+20 more)

### Community 8 - "test_models_db.py"
Cohesion: 0.14
Nodes (36): ContentType, InteractionType, str, ContentItemCreate, ContentItemResponse, InteractionCreate, InteractionResponse, BaseModel (+28 more)

### Community 9 - "test_intelligence_pipeline.py"
Cohesion: 0.13
Nodes (19): IntelligencePipeline, AsyncSession, Runs extraction + topic classification for a creator's collected data., Run intelligence pipeline for a creator. Loads all interactions + evidence,…, FakeProvider, asyncio, AsyncSession, Integration tests for IntelligencePipeline against real Postgres. (+11 more)

### Community 10 - "YouTubeAdapter"
Cohesion: 0.10
Nodes (18): Exception, QuotaExceededError, Resolve a channel handle (e.g. '@mkbhd') to a channel ID., Get comment threads (top-level + replies) for a video., Raised when YouTube API daily quota would be exceeded., Paginate through all replies for a comment thread., Fetch transcript/captions for a video (no quota cost)., Fetch channel-level statistics, snippet, and branding. (+10 more)

### Community 11 - "test_intent_pipeline.py"
Cohesion: 0.16
Nodes (16): IntentPipeline, AsyncSession, Classifies commercial intent for each ProblemCluster., Run intent classification for all clusters. Args: creator_id: Scope to clusters…, FakeProvider, asyncio, AsyncSession, Integration tests for IntentPipeline against real Postgres. (+8 more)

### Community 12 - "SignalLevel"
Cohesion: 0.10
Nodes (37): classify_signal_level(), load_intent_rules(), Any, Path, Rules-table classification. Match indicators against the hierarchy., str, SignalLevel, classify_cluster_intent() (+29 more)

### Community 13 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 14 - "test_extraction.py"
Cohesion: 0.15
Nodes (17): extract_observations(), ExtractedObservation, Per-comment problem/question/pain extraction via LLM., DTO for a single extracted problem observation., Extract problem observations from a single comment. Returns a list of…, FailingProvider, FakeProvider, Unit tests for problem extraction — LLM calls mocked. (+9 more)

### Community 15 - "AccessMethod"
Cohesion: 0.16
Nodes (17): BaseException, create_evidence(), AsyncSession, AccessMethod, ComplianceStatus, str, EvidenceCreate, EvidenceResponse (+9 more)

### Community 16 - "test_dossier_generator.py"
Cohesion: 0.26
Nodes (23): FakeAccount, FakeCluster, FakeCompetitor, FakeCreator, FakeCreatorScore, FakeDataCoverage, FakeObservation, FakeOpportunity (+15 more)

### Community 17 - "LLMProvider"
Cohesion: 0.14
Nodes (12): GeminiProvider, LLMProvider, ABC, LLM provider abstraction with deterministic call logging., Abstract LLM provider with JSON-mode generation., Google Gemini provider using the free tier., _response_hash(), Unit tests for the LLM provider registry. (+4 more)

### Community 18 - "CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1"
Cohesion: 0.10
Nodes (20): 0. What "using CIP" means here, 1. Two findings before you build, 2. Capability decomposition + reuse verdicts, 3. Prior art — five candidate repos (search-before-build gate, executed), 4. The headline: CORP and CIP share DNA, 5. Repo skeleton (respects your import-linter discipline), 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only), 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero) (+12 more)

### Community 19 - "test_youtube_adapter.py"
Cohesion: 0.19
Nodes (18): _comment_threads_response(), _make_adapter(), _playlist_items_response(), Unit tests for the YouTube adapter — all API calls mocked., test_collect_full_flow(), test_get_captions(), test_get_captions_unavailable(), test_get_comment_threads() (+10 more)

### Community 20 - ".list_videos"
Cohesion: 0.33
Nodes (5): _parse_duration(), datetime, List videos from a channel's uploads playlist., Parse ISO 8601 duration (e.g. 'PT4M13S') to total seconds., _list()

### Community 21 - "test_topics.py"
Cohesion: 0.17
Nodes (12): classify_topics(), Topic classification for creator content via LLM., Classify a creator's content into topics. Args: provider: LLM provider…, FailingProvider, FakeProvider, Unit tests for topic classification — LLM calls mocked., test_classify_topics_basic(), test_classify_topics_clamps_confidence() (+4 more)

### Community 22 - "test_collector.py"
Cohesion: 0.22
Nodes (14): _create_creator(), FakeAdapter, asyncio, AsyncSession, Integration tests for AcquisitionCollector against real Postgres., Adapter returning canned NormalizedContent items., Running collection twice should not create duplicate ContentItems., If the adapter raises, the ResearchRun is marked failed. (+6 more)

### Community 23 - "embed_texts"
Cohesion: 0.11
Nodes (18): embed_texts(), Embedder, ndarray, Embedding generation for ProblemObservation text using sentence-transformers., Protocol for anything that can embed text into vectors., Production embedder using sentence-transformers (local, free)., Embed a list of texts in batches. Returns an (N, EMBEDDING_DIM) float32 array., SentenceTransformerEmbedder (+10 more)

### Community 24 - "clean_db"
Cohesion: 0.40
Nodes (5): clean_db(), db_session(), AsyncSession, fixture, Truncate all tables before a test, then yield a fresh session.

### Community 25 - "NormalizedContent"
Cohesion: 0.17
Nodes (9): AcquisitionCollector, AsyncSession, Find the ContentItem a comment/reply belongs to., Update CreatorPlatformAccount with channel-level metadata., Persists adapter output into ContentItem, AudienceInteraction, and Evidence…, Collect all data for a creator and persist to DB. Args: identifier: Platform-…, NormalizedContent, BaseModel (+1 more)

### Community 28 - "load_yaml_rules"
Cohesion: 0.36
Nodes (8): get_rule_version(), load_yaml_rules(), Any, Path, test_get_rule_version(), test_load_intent_rules(), test_load_scoring_rules(), test_missing_file_raises()

### Community 29 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 31 - "CORP Search-Before-Build Checklist"
Cohesion: 0.25
Nodes (7): Commercial-intent signal hierarchy (rules table), CORP Search-Before-Build Checklist, Current Build items (from capability decomposition), Dossier template, For each Build module:, How to run this check for new modules, Normalized adapter output schema

### Community 32 - "test_migration.py"
Cohesion: 0.38
Nodes (6): CompletedProcess, Test that Alembic migrations run clean up and down., Verify migration can go down to base and back up cleanly., run_alembic(), test_migration_current_is_head(), test_migration_downgrade_upgrade()

### Community 33 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 34 - "schemas/intelligence.py"
Cohesion: 0.60
Nodes (4): ProblemClusterResponse, ProblemObservationCreate, ProblemObservationResponse, BaseModel

### Community 36 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 37 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 38 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **105 isolated node(s):** `corp`, `FakeCluster`, `FakeOppScore`, `FakeObservation`, `graphify` (+100 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 354 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LLMProvider` connect `LLMProvider` to `routes.py`, `test_fair_provider.py`, `test_intelligence_pipeline.py`, `test_intent_pipeline.py`, `SignalLevel`, `test_extraction.py`, `test_topics.py`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `SignalLevel` connect `SignalLevel` to `routes.py`, `test_scoring_engine.py`, `test_endpoints.py`, `test_models_db.py`, `test_intent_pipeline.py`, `test_dossier_generator.py`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `AccessMethod` connect `AccessMethod` to `routes.py`, `ClusterPipeline`, `test_endpoints.py`, `test_models_db.py`, `test_intelligence_pipeline.py`, `YouTubeAdapter`, `test_intent_pipeline.py`, `test_collector.py`, `NormalizedContent`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `Creator` (e.g. with `create_decision()` and `get_competitors()`) actually correct?**
  _`Creator` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `SignalLevel` (e.g. with `score_commercial_intent()` and `IntentClassification`) actually correct?**
  _`SignalLevel` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `CreatorStatus` (e.g. with `list_creators()` and `CreatorResponse`) actually correct?**
  _`CreatorStatus` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `ResearchRun` (e.g. with `get_evidence()` and `list_research_runs()`) actually correct?**
  _`ResearchRun` has 13 INFERRED edges - model-reasoned connections that need verification._