# Graph Report - CORP-Creator-Opportunity-Research-Platform  (2026-09-13)

## Corpus Check
- 114 files · ~39,963 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 4, .example 1, .ini 1)

## Summary
- 961 nodes · 2569 edges · 72 communities (38 shown, 7 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 361 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d5d03967`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ResearchRun
- routes.py
- test_scoring_engine.py
- CORP Implementation Steps — Coding Roadmap
- test_fair_provider.py
- test_scoring_pipeline.py
- cluster_pipeline.py
- test_endpoints.py
- test_models_db.py
- test_intelligence_pipeline.py
- YouTubeAdapter
- CommercialSignal
- test_intent_classifier.py
- What You Must Do When Invoked
- test_extraction.py
- AccessMethod
- test_dossier_generator.py
- LLMProvider
- CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1
- test_youtube_adapter.py
- SignalLevel
- test_topics.py
- test_collector.py
- embed_texts
- test_cluster_pipeline.py
- NormalizedContent
- ProblemObservation
- Embedder
- load_yaml_rules
- graphify reference: extra exports and benchmark
- SourceAdapter
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
4. `AccessMethod` - 42 edges
5. `ResearchRun` - 42 edges
6. `ComplianceStatus` - 41 edges
7. `Evidence` - 41 edges
8. `LLMProvider` - 41 edges
9. `ProblemObservation` - 40 edges
10. `DossierGenerator` - 37 edges

## Surprising Connections (you probably didn't know these)
- `FakeSignal` --uses--> `SignalLevel`  [INFERRED]
  tests/workers/test_dossier_generator.py → corp/core/models/intent.py
- `_seed()` --uses--> `CompetitorType`  [INFERRED]
  tests/api/test_endpoints.py → corp/core/models/competitive.py
- `_seed_full()` --uses--> `CompetitorType`  [INFERRED]
  tests/integration/test_dossier_pipeline.py → corp/core/models/competitive.py
- `test_scoring_pipeline_competition_saturation_reflects_competitors()` --uses--> `CompetitorType`  [INFERRED]
  tests/integration/test_scoring_pipeline.py → corp/core/models/competitive.py
- `FakeCompetitor` --uses--> `CompetitorType`  [INFERRED]
  tests/workers/test_dossier_generator.py → corp/core/models/competitive.py

## Import Cycles
- None detected.

## Communities (72 total, 7 thin omitted)

### Community 0 - "ResearchRun"
Cohesion: 0.09
Nodes (44): Base, generate_uuid(), TimestampMixin, Competitor, An existing product/creator/workaround already serving a problem cluster's…, AudienceInteraction, ContentItem, CreatorPlatformAccount (+36 more)

### Community 1 - "routes.py"
Cohesion: 0.09
Nodes (53): create_decision(), get_competitors(), get_creator(), get_dossier(), get_evidence(), get_opportunities(), list_creators(), list_research_runs() (+45 more)

### Community 2 - "test_scoring_engine.py"
Cohesion: 0.06
Nodes (54): CompetitorStrength, CompetitorType, str, CompetitorResponse, BaseModel, compute_hash(), compute_score(), get_score_band() (+46 more)

### Community 3 - "CORP Implementation Steps — Coding Roadmap"
Cohesion: 0.04
Nodes (47): 0.1 Python project setup, 0.2 Database scaffold, 0.3 Directory structure, 0.4 Config, 0.5 CI/test harness, 1.1 Core entities (SQLAlchemy models + Pydantic schemas), 1.2 Alembic migration, 1.3 Tests (+39 more)

### Community 4 - "test_fair_provider.py"
Cohesion: 0.09
Nodes (31): FairProvider, FairProviderError, AsyncClient, Exception, FAIR Free AI Router provider — governed multi-provider LLM backend., FAIR routing failed and no output was returned., LLM provider backed by a FAIR Free AI Router instance. Sends prompts to FAIR's…, accepted_provider() (+23 more)

### Community 5 - "test_scoring_pipeline.py"
Cohesion: 0.13
Nodes (26): ConfidenceBand, str, compute_confidence_band(), Confidence banding driven by YAML thresholds when provided. Args: thresholds:…, AsyncSession, Scores every ProblemCluster as an opportunity, then aggregates per creator., ScoringPipeline, test_custom_thresholds_override_defaults() (+18 more)

### Community 6 - "cluster_pipeline.py"
Cohesion: 0.13
Nodes (31): Clustering pipeline — embed observations, cluster, persist to DB., _build_clusters(), cluster_observations(), ClusteringConfig, ClusterResult, _generate_label(), _pick_representative(), datetime (+23 more)

### Community 7 - "test_endpoints.py"
Cohesion: 0.18
Nodes (28): BaseSettings, create_app(), _get_cors_origins(), FastAPI application factory., Settings, get_session(), AsyncSession, FastAPI (+20 more)

### Community 8 - "test_models_db.py"
Cohesion: 0.19
Nodes (30): ContentType, InteractionType, str, ContentItemCreate, ContentItemResponse, InteractionCreate, InteractionResponse, BaseModel (+22 more)

### Community 9 - "test_intelligence_pipeline.py"
Cohesion: 0.13
Nodes (19): IntelligencePipeline, AsyncSession, Runs extraction + topic classification for a creator's collected data., Run intelligence pipeline for a creator. Loads all interactions + evidence,…, FakeProvider, asyncio, AsyncSession, Integration tests for IntelligencePipeline against real Postgres. (+11 more)

### Community 10 - "YouTubeAdapter"
Cohesion: 0.09
Nodes (19): datetime, Exception, QuotaExceededError, Resolve a channel handle (e.g. '@mkbhd') to a channel ID., List videos from a channel's uploads playlist., Get comment threads (top-level + replies) for a video., Raised when YouTube API daily quota would be exceeded., Paginate through all replies for a comment thread. (+11 more)

### Community 11 - "CommercialSignal"
Cohesion: 0.17
Nodes (17): CommercialSignal, IntentPipeline, Intent classification pipeline — clusters → CommercialSignal rows., Classifies commercial intent for each ProblemCluster., Run intent classification for all clusters. Args: creator_id: Scope to clusters…, FakeProvider, asyncio, AsyncSession (+9 more)

### Community 12 - "test_intent_classifier.py"
Cohesion: 0.13
Nodes (20): classify_cluster_intent(), IntentClassification, _llm_classify(), Take the higher of rules-table and LLM classifications., DTO for a classified commercial signal., Classify a problem cluster's commercial intent. Uses both LLM classification…, _reconcile(), FailingProvider (+12 more)

### Community 13 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 14 - "test_extraction.py"
Cohesion: 0.15
Nodes (17): extract_observations(), ExtractedObservation, Per-comment problem/question/pain extraction via LLM., DTO for a single extracted problem observation., Extract problem observations from a single comment. Returns a list of…, FailingProvider, FakeProvider, Unit tests for problem extraction — LLM calls mocked. (+9 more)

### Community 15 - "AccessMethod"
Cohesion: 0.20
Nodes (17): BaseException, create_evidence(), AsyncSession, AccessMethod, ComplianceStatus, Evidence, str, Append-only evidence store. No UPDATE or DELETE — ever. (+9 more)

### Community 16 - "test_dossier_generator.py"
Cohesion: 0.26
Nodes (23): FakeAccount, FakeCluster, FakeCompetitor, FakeCreator, FakeCreatorScore, FakeDataCoverage, FakeObservation, FakeOpportunity (+15 more)

### Community 17 - "LLMProvider"
Cohesion: 0.12
Nodes (13): AsyncSession, GeminiProvider, LLMProvider, ABC, LLM provider abstraction with deterministic call logging., Abstract LLM provider with JSON-mode generation., Google Gemini provider using the free tier., _response_hash() (+5 more)

### Community 18 - "CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1"
Cohesion: 0.10
Nodes (20): 0. What "using CIP" means here, 1. Two findings before you build, 2. Capability decomposition + reuse verdicts, 3. Prior art — five candidate repos (search-before-build gate, executed), 4. The headline: CORP and CIP share DNA, 5. Repo skeleton (respects your import-linter discipline), 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only), 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero) (+12 more)

### Community 19 - "test_youtube_adapter.py"
Cohesion: 0.19
Nodes (18): _comment_threads_response(), _make_adapter(), _playlist_items_response(), Unit tests for the YouTube adapter — all API calls mocked., test_collect_full_flow(), test_get_captions(), test_get_captions_unavailable(), test_get_comment_threads() (+10 more)

### Community 20 - "SignalLevel"
Cohesion: 0.22
Nodes (17): classify_signal_level(), load_intent_rules(), Any, Path, Rules-table classification. Match indicators against the hierarchy., str, SignalLevel, Path (+9 more)

### Community 21 - "test_topics.py"
Cohesion: 0.17
Nodes (12): classify_topics(), Topic classification for creator content via LLM., Classify a creator's content into topics. Args: provider: LLM provider…, FailingProvider, FakeProvider, Unit tests for topic classification — LLM calls mocked., test_classify_topics_basic(), test_classify_topics_clamps_confidence() (+4 more)

### Community 22 - "test_collector.py"
Cohesion: 0.22
Nodes (14): _create_creator(), FakeAdapter, asyncio, AsyncSession, Integration tests for AcquisitionCollector against real Postgres., Adapter returning canned NormalizedContent items., Running collection twice should not create duplicate ContentItems., If the adapter raises, the ResearchRun is marked failed. (+6 more)

### Community 23 - "embed_texts"
Cohesion: 0.19
Nodes (12): embed_texts(), Embedding generation for ProblemObservation text using sentence-transformers., Embed a list of texts in batches. Returns an (N, EMBEDDING_DIM) float32 array., FakeEmbedder, ndarray, Unit tests for embeddings module — no model download needed., Deterministic embedder returning fixed-dimension vectors., test_embed_texts_basic() (+4 more)

### Community 24 - "test_cluster_pipeline.py"
Cohesion: 0.27
Nodes (14): FakeEmbedder, asyncio, AsyncSession, ndarray, Integration tests for ClusterPipeline against real Postgres., Returns embeddings with clear cluster structure for testing., Create a creator with multiple ProblemObservation groups., _seed_observations() (+6 more)

### Community 25 - "NormalizedContent"
Cohesion: 0.23
Nodes (7): AcquisitionCollector, Find the ContentItem a comment/reply belongs to., Persists adapter output into ContentItem, AudienceInteraction, and Evidence…, Collect all data for a creator and persist to DB. Args: identifier: Platform-…, NormalizedContent, BaseModel, The one schema both adapter families emit. This is the Build item.

### Community 26 - "ProblemObservation"
Cohesion: 0.29
Nodes (7): ProblemClusterMember, ProblemObservation, ClusterPipeline, datetime, ndarray, Embeds ProblemObservations, clusters them, and persists results., Run clustering pipeline. Args: creator_id: Scope to a single creator, or None…

### Community 27 - "Embedder"
Cohesion: 0.17
Nodes (7): AsyncSession, Embedder, ndarray, Protocol for anything that can embed text into vectors., Production embedder using sentence-transformers (local, free)., SentenceTransformerEmbedder, Protocol

### Community 28 - "load_yaml_rules"
Cohesion: 0.36
Nodes (8): get_rule_version(), load_yaml_rules(), Any, Path, test_get_rule_version(), test_load_intent_rules(), test_load_scoring_rules(), test_missing_file_raises()

### Community 29 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 30 - "SourceAdapter"
Cohesion: 0.22
Nodes (4): AsyncSession, ABC, Abstract interface for all source adapters., SourceAdapter

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
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 349 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LLMProvider` connect `LLMProvider` to `ResearchRun`, `test_fair_provider.py`, `test_intelligence_pipeline.py`, `CommercialSignal`, `test_intent_classifier.py`, `test_extraction.py`, `SignalLevel`, `test_topics.py`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Why does `SignalLevel` connect `SignalLevel` to `ResearchRun`, `test_scoring_engine.py`, `test_scoring_pipeline.py`, `test_endpoints.py`, `test_models_db.py`, `CommercialSignal`, `test_intent_classifier.py`, `test_dossier_generator.py`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `AccessMethod` connect `AccessMethod` to `ResearchRun`, `test_scoring_pipeline.py`, `test_endpoints.py`, `test_models_db.py`, `test_intelligence_pipeline.py`, `YouTubeAdapter`, `CommercialSignal`, `test_collector.py`, `test_cluster_pipeline.py`, `NormalizedContent`, `SourceAdapter`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `Creator` (e.g. with `create_decision()` and `get_competitors()`) actually correct?**
  _`Creator` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `SignalLevel` (e.g. with `score_commercial_intent()` and `IntentClassification`) actually correct?**
  _`SignalLevel` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `CreatorStatus` (e.g. with `list_creators()` and `CreatorResponse`) actually correct?**
  _`CreatorStatus` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `AccessMethod` (e.g. with `create_evidence()` and `EvidenceCreate`) actually correct?**
  _`AccessMethod` has 21 INFERRED edges - model-reasoned connections that need verification._