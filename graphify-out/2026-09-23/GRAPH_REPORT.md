# Graph Report - CORP-Creator-Opportunity-Research-Platform  (2026-09-13)

## Corpus Check
- 120 files · ~42,856 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 4, .example 1, .ini 1)

## Summary
- 1021 nodes · 2751 edges · 75 communities (39 shown, 6 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 417 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ba46ff3a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Creator
- CreatorStatus
- test_scoring_engine.py
- CORP Implementation Steps — Coding Roadmap
- test_fair_provider.py
- ConfidenceBand
- ClusteringConfig
- test_endpoints.py
- test_models_db.py
- test_intelligence_pipeline.py
- YouTubeAdapter
- Evidence
- test_intent_classifier.py
- What You Must Do When Invoked
- test_extraction.py
- AccessMethod
- test_dossier_generator.py
- LLMProvider
- CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1
- test_youtube_adapter.py
- test_cluster_pipeline.py
- test_topics.py
- test_collector.py
- embed_texts
- clean_db
- NormalizedContent
- SignalLevel
- load_yaml_rules
- graphify reference: extra exports and benchmark
- CORP Search-Before-Build Checklist
- test_migration.py
- graphify reference: query, path, explain
- routes.py
- cluster_observations
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- CORP — Creator Opportunity Research Platform
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- .claude/CLAUDE.md
- extraction-spec.md
- corp
- ClusterPipeline
- Embedder

## God Nodes (most connected - your core abstractions)
1. `Creator` - 51 edges
2. `SignalLevel` - 50 edges
3. `ResearchRun` - 49 edges
4. `Evidence` - 47 edges
5. `ProblemObservation` - 45 edges
6. `LLMProvider` - 45 edges
7. `CreatorStatus` - 44 edges
8. `AccessMethod` - 43 edges
9. `ComplianceStatus` - 42 edges
10. `ProblemCluster` - 40 edges

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

## Communities (75 total, 6 thin omitted)

### Community 0 - "Creator"
Cohesion: 0.07
Nodes (73): create_decision(), Base, generate_uuid(), TimestampMixin, Competitor, CompetitorType, An existing product/creator/workaround already serving a problem cluster's…, AudienceInteraction (+65 more)

### Community 1 - "CreatorStatus"
Cohesion: 0.23
Nodes (21): CreatorStatus, str, Gate A logic — human review decisions with state machine transitions., InvalidTransitionError, Exception, validate_transition(), Unit tests for Gate A state transitions., test_decision_type_maps_to_status() (+13 more)

### Community 2 - "test_scoring_engine.py"
Cohesion: 0.06
Nodes (55): CompetitorStrength, str, compute_hash(), compute_score(), get_score_band(), load_scoring_rules(), Any, Higher = more whitespace (less saturated), matching the "higher is better"… (+47 more)

### Community 3 - "CORP Implementation Steps — Coding Roadmap"
Cohesion: 0.04
Nodes (47): 0.1 Python project setup, 0.2 Database scaffold, 0.3 Directory structure, 0.4 Config, 0.5 CI/test harness, 1.1 Core entities (SQLAlchemy models + Pydantic schemas), 1.2 Alembic migration, 1.3 Tests (+39 more)

### Community 4 - "test_fair_provider.py"
Cohesion: 0.09
Nodes (31): FairProvider, FairProviderError, AsyncClient, Exception, FAIR Free AI Router provider — governed multi-provider LLM backend., FAIR routing failed and no output was returned., LLM provider backed by a FAIR Free AI Router instance. Sends prompts to FAIR's…, accepted_provider() (+23 more)

### Community 5 - "ConfidenceBand"
Cohesion: 0.37
Nodes (11): ConfidenceBand, str, compute_confidence_band(), Confidence banding driven by YAML thresholds when provided. Args: thresholds:…, test_custom_thresholds_override_defaults(), test_high_confidence(), test_insufficient_low_evidence(), test_insufficient_no_sources() (+3 more)

### Community 6 - "ClusteringConfig"
Cohesion: 0.16
Nodes (15): ClusteringConfig, _pick_representative(), Pick the longest text as the representative description., Tunable clustering parameters., _make_clustered_embeddings(), ndarray, Unit tests for clustering — uses synthetic embeddings with known structure., Generate synthetic embeddings with clear cluster structure. (+7 more)

### Community 7 - "test_endpoints.py"
Cohesion: 0.18
Nodes (28): BaseSettings, create_app(), _get_cors_origins(), FastAPI application factory., Settings, get_session(), AsyncSession, FastAPI (+20 more)

### Community 8 - "test_models_db.py"
Cohesion: 0.19
Nodes (30): ContentType, InteractionType, str, ContentItemCreate, ContentItemResponse, InteractionCreate, InteractionResponse, BaseModel (+22 more)

### Community 9 - "test_intelligence_pipeline.py"
Cohesion: 0.11
Nodes (22): IntelligencePipeline, AsyncSession, Extract observations from a group of comments in batches., Pick the best evidence row for a batch-extracted observation., Load the most recent Evidence row for each external_id., Runs extraction + topic classification for a creator's collected data., Run intelligence pipeline for a creator. Loads all interactions + evidence,…, FakeProvider (+14 more)

### Community 10 - "YouTubeAdapter"
Cohesion: 0.08
Nodes (22): _parse_duration(), datetime, _RateLimiter, Resolve a channel handle (e.g. '@mkbhd') to a channel ID., List videos from a channel's uploads playlist., Get comment threads (top-level + replies) for a video., Parse ISO 8601 duration (e.g. 'PT4M13S') to total seconds., Paginate through all replies for a comment thread. (+14 more)

### Community 11 - "Evidence"
Cohesion: 0.15
Nodes (19): create_evidence(), AsyncSession, Evidence, Append-only evidence store. No UPDATE or DELETE — ever., IntentPipeline, Classifies commercial intent for each ProblemCluster., Run intent classification for all clusters. Args: creator_id: Scope to clusters…, FakeProvider (+11 more)

### Community 12 - "test_intent_classifier.py"
Cohesion: 0.14
Nodes (17): classify_cluster_intent(), Take the higher of rules-table and LLM classifications., Classify a problem cluster's commercial intent. Uses both LLM classification…, _reconcile(), FailingProvider, FakeProvider, Unit tests for commercial intent classification — LLM calls mocked., test_classify_cluster_intent_basic() (+9 more)

### Community 13 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 14 - "test_extraction.py"
Cohesion: 0.13
Nodes (20): extract_observations(), extract_observations_batch(), ExtractedObservation, _parse_observation(), Problem/question/pain extraction via LLM — single and batch modes., Extract problem observations from a single comment., Extract observations from a batch of comments with cross-comment synthesis.…, DTO for a single extracted problem observation. (+12 more)

### Community 15 - "AccessMethod"
Cohesion: 0.17
Nodes (16): BaseException, AccessMethod, ComplianceStatus, str, EvidenceCreate, EvidenceResponse, BaseModel, ABC (+8 more)

### Community 16 - "test_dossier_generator.py"
Cohesion: 0.26
Nodes (23): FakeAccount, FakeCluster, FakeCompetitor, FakeCreator, FakeCreatorScore, FakeDataCoverage, FakeObservation, FakeOpportunity (+15 more)

### Community 17 - "LLMProvider"
Cohesion: 0.11
Nodes (14): AsyncSession, AsyncSession, GeminiProvider, LLMProvider, ABC, LLM provider abstraction with deterministic call logging., Abstract LLM provider with JSON-mode generation., Google Gemini provider using the free tier. (+6 more)

### Community 18 - "CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1"
Cohesion: 0.10
Nodes (20): 0. What "using CIP" means here, 1. Two findings before you build, 2. Capability decomposition + reuse verdicts, 3. Prior art — five candidate repos (search-before-build gate, executed), 4. The headline: CORP and CIP share DNA, 5. Repo skeleton (respects your import-linter discipline), 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only), 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero) (+12 more)

### Community 19 - "test_youtube_adapter.py"
Cohesion: 0.15
Nodes (21): Exception, QuotaExceededError, Raised when YouTube API daily quota would be exceeded., _comment_threads_response(), _make_adapter(), _playlist_items_response(), Unit tests for the YouTube adapter — all API calls mocked., test_collect_full_flow() (+13 more)

### Community 20 - "test_cluster_pipeline.py"
Cohesion: 0.27
Nodes (14): FakeEmbedder, asyncio, AsyncSession, ndarray, Integration tests for ClusterPipeline against real Postgres., Returns embeddings with clear cluster structure for testing., Create a creator with multiple ProblemObservation groups., _seed_observations() (+6 more)

### Community 21 - "test_topics.py"
Cohesion: 0.17
Nodes (12): classify_topics(), Topic classification for creator content via LLM., Classify a creator's content into topics. Args: provider: LLM provider…, FailingProvider, FakeProvider, Unit tests for topic classification — LLM calls mocked., test_classify_topics_basic(), test_classify_topics_clamps_confidence() (+4 more)

### Community 22 - "test_collector.py"
Cohesion: 0.22
Nodes (14): _create_creator(), FakeAdapter, asyncio, AsyncSession, Integration tests for AcquisitionCollector against real Postgres., Adapter returning canned NormalizedContent items., Running collection twice should not create duplicate ContentItems., If the adapter raises, the ResearchRun is marked failed. (+6 more)

### Community 23 - "embed_texts"
Cohesion: 0.19
Nodes (12): embed_texts(), Embedding generation for ProblemObservation text using sentence-transformers., Embed a list of texts in batches. Returns an (N, EMBEDDING_DIM) float32 array., FakeEmbedder, ndarray, Unit tests for embeddings module — no model download needed., Deterministic embedder returning fixed-dimension vectors., test_embed_texts_basic() (+4 more)

### Community 24 - "clean_db"
Cohesion: 0.40
Nodes (5): clean_db(), db_session(), AsyncSession, fixture, Truncate all tables before a test, then yield a fresh session.

### Community 25 - "NormalizedContent"
Cohesion: 0.17
Nodes (9): AcquisitionCollector, AsyncSession, Find the ContentItem a comment/reply belongs to., Update CreatorPlatformAccount with channel-level metadata., Persists adapter output into ContentItem, AudienceInteraction, and Evidence…, Collect all data for a creator and persist to DB. Args: identifier: Platform-…, NormalizedContent, BaseModel (+1 more)

### Community 27 - "SignalLevel"
Cohesion: 0.19
Nodes (20): classify_signal_level(), load_intent_rules(), Any, Path, Rules-table classification. Match indicators against the hierarchy., str, SignalLevel, IntentClassification (+12 more)

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

### Community 34 - "routes.py"
Cohesion: 0.11
Nodes (42): get_clusters(), get_competitors(), get_creator(), get_dossier(), get_dossier_json(), get_evidence(), get_observations(), get_opportunities() (+34 more)

### Community 35 - "cluster_observations"
Cohesion: 0.19
Nodes (15): _build_clusters(), cluster_observations(), ClusterResult, _fit_bertopic(), get_topic_labels(), datetime, ndarray, Problem observation clustering via BERTopic (UMAP + HDBSCAN + c-TF-IDF). (+7 more)

### Community 36 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 37 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 38 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 72 - "ClusterPipeline"
Cohesion: 0.24
Nodes (6): ClusterPipeline, datetime, ndarray, Merge BERTopic cluster labels into the creator's ContentItem topics. Produces a…, Embeds ProblemObservations, clusters them, and persists results., Run clustering pipeline. Args: creator_id: Scope to a single creator, or None…

### Community 73 - "Embedder"
Cohesion: 0.17
Nodes (7): AsyncSession, Embedder, ndarray, Protocol for anything that can embed text into vectors., Production embedder using sentence-transformers (local, free)., SentenceTransformerEmbedder, Protocol

## Knowledge Gaps
- **105 isolated node(s):** `corp`, `FakeCluster`, `FakeOppScore`, `FakeObservation`, `graphify` (+100 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 373 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LLMProvider` connect `LLMProvider` to `Creator`, `test_fair_provider.py`, `test_intelligence_pipeline.py`, `Evidence`, `test_intent_classifier.py`, `test_extraction.py`, `AccessMethod`, `test_topics.py`, `SignalLevel`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Why does `ComplianceStatus` connect `AccessMethod` to `Creator`, `test_endpoints.py`, `test_models_db.py`, `test_intelligence_pipeline.py`, `YouTubeAdapter`, `Evidence`, `test_cluster_pipeline.py`, `test_collector.py`, `NormalizedContent`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `AccessMethod` connect `AccessMethod` to `Creator`, `test_endpoints.py`, `test_models_db.py`, `test_intelligence_pipeline.py`, `YouTubeAdapter`, `Evidence`, `test_cluster_pipeline.py`, `test_collector.py`, `NormalizedContent`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `Creator` (e.g. with `create_decision()` and `get_clusters()`) actually correct?**
  _`Creator` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `SignalLevel` (e.g. with `CommercialSignalResponse` and `score_commercial_intent()`) actually correct?**
  _`SignalLevel` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `ResearchRun` (e.g. with `get_clusters()` and `get_evidence()`) actually correct?**
  _`ResearchRun` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Evidence` (e.g. with `get_clusters()` and `get_evidence()`) actually correct?**
  _`Evidence` has 13 INFERRED edges - model-reasoned connections that need verification._