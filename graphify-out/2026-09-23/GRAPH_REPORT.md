# Graph Report - CORP-Creator-Opportunity-Research-Platform  (2026-09-23)

## Corpus Check
- 387 files · ~234,391 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 5, .example 2, .ini 1)

## Summary
- 5164 nodes · 14958 edges · 288 communities (226 shown, 62 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 2303 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ccc01da4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- OpportunityScore
- CreatorStatus
- test_scoring_engine.py
- CORP Implementation Steps — Coding Roadmap
- test_fair_provider.py
- ConfidenceBand
- integration/test_cluster_pipeline.py
- test_endpoints.py
- test_models_db.py
- IntelligencePipeline
- YouTubeAdapter
- Evidence
- SignalLevel
- What You Must Do When Invoked
- extract_observations
- ComplianceStatus
- test_dossier_generator.py
- test_provider_registry.py
- CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1
- test_youtube_adapter.py
- test_niche_discovery.py
- LLMCallError
- AcquisitionCollector
- Embedder
- Niche
- ._persist_items
- MarketplaceAdapter
- load_yaml_rules
- graphify reference: extra exports and benchmark
- CORP Search-Before-Build Checklist
- test_migration.py
- graphify reference: query, path, explain
- schemas/dossier.py
- build_provider
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- CORP — Creator Opportunity Research Platform
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- .claude/CLAUDE.md
- extraction-spec.md
- corp
- ResearchRun
- run.py
- WarmStore
- AmazonReviewAdapter
- CreatorOnboarder
- PatreonSubstackAdapter
- test_coerce.py
- AppStoreAdapter
- test_stackexchange_adapter.py
- EvidenceType
- ProviderExhaustedError
- test_watch_rescanner.py
- CrowdfundingAdapter
- GoogleTrendsAdapter
- WikipediaAdapter
- Creator
- test_registry_rescan.py
- test_dossier_decision_endpoint.py
- test_web_adapter.py
- routes_ops.py
- YtDlpAdapter
- .select
- SearchDemandAdapter
- SourceHealthTracker
- HackerNewsAdapter
- test_corp2_export.py
- register_error_handlers
- ._score_opportunity
- test_runs.py
- app.py
- test_ops_no_db.py
- test_niche_candidates.py
- test_discovery.py
- CampaignResearchBatch
- App.tsx
- CreatorDetailPage.tsx
- EcosystemEstimator
- test_provider_health.py
- test_product_ideation.py
- hooks.ts
- EvidenceOrigin
- NormalizedContent
- scoring/niche_qualification.py
- test_dossier_persistence.py
- require_api_key
- record_query
- test_niche_naming.py
- test_groq_provider.py
- test_multi_discovery.py
- NicheLifecycleStatus
- ProblemCluster
- package.json
- test_niche_canonicalization.py
- providers/registry.py
- Campaign
- MultiSourceDiscovery
- test_captions.py
- ResearchOrchestrator
- RegistryRescanScheduler
- test_campaign_endpoints.py
- test_reddit_adapter.py
- CompetitivePipeline
- CampaignDetailPage.tsx
- matched_exclusion
- 3. Product specification (Stage 3 — to freeze)
- ScriptedProvider
- .generate
- compute_score
- compilerOptions
- NicheQualifier
- PruneService
- DecisionType
- build_adapter
- Ideator
- compilerOptions
- test_discovery_scan.py
- ProblemObservation
- NichePolicyClass
- product_ideation.py
- Decisions
- ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator
- _seed_full
- ADR-0040 — CORP1 Stage 5, T10: Registry Re-scan Scheduler
- ADR-0034 — CORP1 Stage 5, T4: Campaign Pipeline Rewire
- ADR-0042 — CORP1 Stage 5, T13: Kickstarter + Indiegogo Adapter (Phase 2.3)
- test_creator_archive.py
- client.ts
- ADR-0030 — CORP1 Stage 4, T0: Niche Drill-Down Tree + Dossier Model
- ADR-0032 — CORP1 Stage 5, T2: Wrap Existing Adapters
- ADR-0037 — CORP1 Stage 5, T7: Scoring Engine Update
- ADR-0038 — CORP1 Stage 5, T8: Four-State Decision Gate
- ADR-0039 — CORP1 Stage 5, T9: CORP2 Handoff Package
- ADR-0043 — CORP1 Stage 5, T14: Patreon + Substack Adapter (Phase 2.4)
- ADR-0044 — CORP1 Stage 5, T21: Full Scoring Integration (Phase 3.6)
- ADR-0045 — Wire Registry Re-scan Scheduler into App Startup
- Running CORP locally (laptop + flash drive)
- test_handoff_endpoint.py
- Slice 7 — Niche Discovery Light: One Source
- ADR-0031 — CORP1 Stage 5, T1: Capability-Provider Interfaces
- ADR-0035 — CORP1 Stage 5, T5: Product Idea Generation
- YouTubeAPIEnricher
- _days_from_recency
- Slice 19 — WarmStore Foundation
- ADR-0046 — Wire T9 Handoff to T8's Approve Decision Path
- ADR-0047 — Fix DossierGenerator Cross-Niche Opportunity Mismatch
- devDependencies
- CreatorsPage.tsx
- test_intelligence_pipeline.py
- decide_resurface
- Slice 18 — Creator Intelligence Dashboard
- Slice 20 — WarmStore Pipeline Integration
- Slice 21 — YouTube Transcript Segmentation
- Decision
- Decision
- ADR-0059 — R11b: yt-dlp type stubs; triage of the five "pre-existing" test failures
- CORP — Creator Opportunity Research Platform
- Slice 17 — Campaign Pipeline API + Campaign Dashboard UI
- ADR-0028 — Slice 25: Remaining Licensed/Tolerated Niche-Signal Adapters
- ADR-0048 — R1: Evidence-type fallback mapping keyed on real adapter platform strings
- ADR-0049 — R2: LLM-derived Evidence rows carry `origin = INFERENCE`
- ADR-0050 — R3: Backfill Evidence provenance and enforce it at the database
- ADR-0051 — R6: Scope dossier demand validation to the niche's own evidence
- ADR-0052 — R4: Carry drill lineage onto Niche.parent_niche_id / depth
- ADR-0053 — R5: Depth cap on research_more, full fan-out, registry clock at promotion, EXCLUDED lifecycle
- ADR-0054 — R8: Re-scan scheduler — clock on success only, savepoint per dossier, resurface only on change
- ADR-0055 — R9: Gate A returns 422 for an invalid decision or foreign opportunity score
- ADR-0056 — R7: Surface the enriched dossier content in the UI and the HTML dossier
- ADR-0057 — R10: Frontend/API correctness batch
- ADR-0058 — R11: Project-wide static gates clean, model/migration defaults aligned
- ADR-0060 — R12b: Creator.status mirrors the dossier decision gate
- ADR-0061 — R12a: Research More completes through a shared WatchRescanner; product ideation wired
- CORP1 Remediation Plan — Spec Alignment (September 2026)
- Slice 3 — Campaign ↔ Niche Relationship
- Slice 4 — Creator ↔ Niche Relationship
- Slice 6 — Research Query Ledger
- Provider pool: Gemini daily cap + Groq failover
- FAIR as an in-process provider; prompts carry their answer schema
- Slice 8 — Evidence → Candidate Niche
- ADR-0025 — Slice 22: Stack Exchange Niche-Signal Adapter
- ADR-0027 — Slice 24: Marketplace Listings Adapter (Gumroad / Etsy / Udemy)
- ADR-0062 — R12c: the Watch re-scan scheduler re-researches through the WatchRescanner under per-tick limits
- ADR-0063 — R12d: the re-scan outcome is visible in the dossier panel and on the Re-scan page
- ADR-0064 — R14: reversible creator archive, respecting the append-only evidence trail
- test_evidence_provenance_constructors.py
- DiscoveryScanScheduler
- Settings
- score_purchase_intent
- Slice 1 — Campaign Persistence
- Slice 2 — Canonical Niche Persistence
- Slice 5 — Generalize ResearchRun
- Slice 9 — Niche Canonicalization & Deduplication
- Slice 10 — Niche Verification
- Slice 11 — Creator Ecosystem Size Estimator
- Slice 12 — Niche Qualification Scoring
- Slice 13 — Niche Selection
- Slice 14 — Creator Onboarding from Selected Niches
- Slice 15 — Campaign Research Batch
- Slice 16 — Campaign & Niche API Visibility
- 2. Capability decomposition + reuse verdicts
- Step 0 — Project Scaffold (Adopt CIP)
- .oxlintrc.json
- CampaignStatus
- test_discovery_endpoint.py
- finish_run returns a status; a fully failed run is kept
- Step 2 — YouTube Adapter (Wrap google-api-python-client)
- Step 3 — Content + Audience Intelligence (Wrap Gemini)
- Step 6 — Scoring + Confidence (Adapt CIP Steps 9 + 12)
- Step 8 — Minimal Console + Gate A (Mirror CIP Step 14)
- stub_fair
- CreatorNicheResponse
- StackExchangeAdapter
- Step 1 — Core Data Model (Adapt CIP Evidence Model)
- Step 4 — Problem Clustering (Adopt BERTopic / HDBSCAN)
- Step 5 — Commercial Intent (Build rules table + Wrap Gemini)
- React + TypeScript + Vite
- test_trend_scan.py
- tsconfig.json
- .record_step
- sync.py
- trend_scan.py
- load_scoring_rules
- ._get_engine
- LLMProvider
- jobs.py
- _score_from_items
- test_mirror_embeddings.py
- PooledProvider
- CompetitorStrength
- patched_pipeline
- score_audience_dissatisfaction
- score_audience_problem_frequency
- ._restore_if_in_progress

## God Nodes (most connected - your core abstractions)
1. `NormalizedContent` - 210 edges
2. `ResearchRun` - 178 edges
3. `ComplianceStatus` - 158 edges
4. `AccessMethod` - 157 edges
5. `Niche` - 155 edges
6. `Creator` - 132 edges
7. `Evidence` - 128 edges
8. `Campaign` - 104 edges
9. `CreatorStatus` - 104 edges
10. `EvidenceType` - 96 edges

## Surprising Connections (you probably didn't know these)
- `FakeSignal` --uses--> `SignalLevel`  [INFERRED]
  tests/workers/test_dossier_generator.py → corp/core/models/intent.py
- `captured()` --uses--> `JobRegistry`  [INFERRED]
  tests/api/test_discovery_endpoint.py → corp/api/jobs.py
- `test_run_pipeline_unknown_kind_raises()` --calls--> `run_pipeline()`  [EXTRACTED]
  tests/api/test_ops_no_db.py → corp/api/jobs.py
- `fake_fair()` --uses--> `Settings`  [INFERRED]
  tests/workers/test_provider_factory.py → corp/config.py
- `clean_db()` --uses--> `Base`  [INFERRED]
  tests/conftest.py → corp/core/models/base.py

## Import Cycles
- None detected.

## Communities (288 total, 62 thin omitted)

### Community 0 - "OpportunityScore"
Cohesion: 0.21
Nodes (21): OpportunityScore, Any, Scores every active ProblemCluster for a creator, then aggregates per creator., Load the strength of every Competitor row known for this cluster. Independent…, ScoringPipeline, asyncio, AsyncSession, Integration tests for ScoringPipeline against real Postgres. (+13 more)

### Community 1 - "CreatorStatus"
Cohesion: 0.12
Nodes (42): CreatorStatus, str, creator_status_for_dossiers(), mirror_creator_status(), Gate A logic — human review decisions with state machine transitions — and the…, The creator status implied by its ACTIVE dossiers, by precedence: any approved…, Move Creator.status to match the creator's active dossiers after a dossier-gate…, InvalidTransitionError (+34 more)

### Community 2 - "test_scoring_engine.py"
Cohesion: 0.08
Nodes (40): get_score_band(), Any, From TrendProvider + SearchIntentProvider evidence (Google Trends interest,…, Higher = less saturated = more room, from SolutionProvider evidence…, score_commercial_intent(), score_creator_reach(), score_evidence_depth(), score_external_demand_strength() (+32 more)

### Community 3 - "CORP Implementation Steps — Coding Roadmap"
Cohesion: 0.22
Nodes (9): 7.1 Dossier template (`workers/dossier/templates/dossier.html.j2`), 7.2 Dossier engine (`workers/dossier/generator.py`), 7.3 Tests, CORP Implementation Steps — Coding Roadmap, Deferred (Only If Thin Slice Earns It), Implementation Order & Dependencies, Key Architectural Decisions (Pre-resolved), Phasing Strategy (+1 more)

### Community 4 - "test_fair_provider.py"
Cohesion: 0.09
Nodes (42): FairProvider, _model_label(), LLMProvider backed by an in-process FAIR router. ``router`` is a…, The model that answered the last call (vendor-canonical label, e.g.…, Every model FAIR may route to, plus the pre-call label: one family for…, _accepted(), Attempt, FakeFair (+34 more)

### Community 5 - "ConfidenceBand"
Cohesion: 0.27
Nodes (15): ConfidenceBand, str, compute_confidence_band(), Any, Confidence banding driven by YAML thresholds when provided. Args: thresholds:…, Regression: 90-365 days used to silently fall through to MEDIUM instead of…, test_custom_thresholds_override_defaults(), test_degrades_to_low_past_medium_max_days() (+7 more)

### Community 6 - "integration/test_cluster_pipeline.py"
Cohesion: 0.09
Nodes (46): _build_clusters(), cluster_observations(), ClusteringConfig, _generate_label(), _pick_representative(), datetime, ndarray, Problem observation clustering via UMAP + HDBSCAN with c-TF-IDF labeling. (+38 more)

### Community 7 - "test_endpoints.py"
Cohesion: 0.18
Nodes (35): create_app(), health(), No-DB tests for the FastAPI application factory's docs/schema exposure., test_docs_disabled_when_api_key_configured(), test_docs_open_when_no_api_key(), _make_client(), AsyncClient, asyncio (+27 more)

### Community 8 - "test_models_db.py"
Cohesion: 0.10
Nodes (59): _create_campaign_and_niche(), _create_creator(), _create_evidence(), asyncio, AsyncSession, Integration tests: models against real Postgres 16. Tests model creation,…, The one rule this slice enforces at the DB level (§11)., The existing, designed cross-creator clustering capability… (+51 more)

### Community 9 - "IntelligencePipeline"
Cohesion: 0.12
Nodes (13): IntelligencePipeline, Any, Extract per-comment + cross-comment observations, one content item at a time.…, Run one batched extraction and persist its observations., Mark an interaction as extracted under the current prompt + model., True when this interaction was already extracted by the current prompt version…, Save single-comment observations against a specific evidence row., Newest evidence row for a source id (re-collection appends, never updates). (+5 more)

### Community 10 - "YouTubeAdapter"
Cohesion: 0.07
Nodes (25): _extract_channel_id(), _http_error_reason(), _parse_iso8601_duration(), Any, datetime, retry, _RateLimiter, Collects videos, comments, and captions from a YouTube channel. (+17 more)

### Community 11 - "Evidence"
Cohesion: 0.21
Nodes (17): Evidence, Append-only evidence store. No UPDATE or DELETE — ever., CommercialSignal, IntentPipeline, Classifies commercial intent for each active ProblemCluster. Runs inside the…, FakeProvider, asyncio, AsyncSession (+9 more)

### Community 12 - "SignalLevel"
Cohesion: 0.08
Nodes (46): classify_signal_level(), load_intent_rules(), _matches_keyword(), Any, Path, Whole-word/phrase match, case-insensitive. A bare substring test made "vs" fire…, Rules-table classification. Match indicators against the hierarchy., str (+38 more)

### Community 13 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 14 - "extract_observations"
Cohesion: 0.16
Nodes (15): extract_observations(), Extract problem observations from a single comment. Raises ``LLMCallError``…, FailingProvider, FakeProvider, Unit tests for problem extraction — LLM calls mocked., A dead provider must not look like an empty comment., Returns canned JSON responses., test_extract_observations_basic() (+7 more)

### Community 15 - "ComplianceStatus"
Cohesion: 0.05
Nodes (78): create_evidence(), AsyncSession, AccessMethod, ComplianceStatus, str, EvidenceCreate, EvidenceResponse, BaseModel (+70 more)

### Community 16 - "test_dossier_generator.py"
Cohesion: 0.22
Nodes (28): FakeAccount, FakeCluster, FakeCompetitor, FakeCreator, FakeCreatorScore, FakeDataCoverage, FakeObservation, FakeOpportunity (+20 more)

### Community 17 - "test_provider_registry.py"
Cohesion: 0.10
Nodes (27): classify_quota_error(), BaseException, Turn a Gemini 429 into a pool signal. Gemini reports a per-day cap and a per-…, _response_hash(), _client_error(), _FakeClient, gemini(), make() (+19 more)

### Community 18 - "CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1"
Cohesion: 0.14
Nodes (14): 0. What "using CIP" means here, 1. Two findings before you build, 3. Prior art — five candidate repos (search-before-build gate, executed), 4. The headline: CORP and CIP share DNA, 5. Repo skeleton (respects your import-linter discipline), 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only), 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero), 8. Open decisions for you (+6 more)

### Community 19 - "test_youtube_adapter.py"
Cohesion: 0.13
Nodes (24): Exception, QuotaExceededError, Raised when YouTube API daily quota would be exceeded., _comment_threads_response(), _make_adapter(), _playlist_items_response(), Unit tests for the YouTube adapter — all API calls mocked., CORP1 Stage 4/5, T2: YouTube is ProblemProvider, delegating to collect(). (+16 more)

### Community 20 - "test_niche_discovery.py"
Cohesion: 0.19
Nodes (46): NicheCandidate, Broad topic -> capability fan-out -> LLM synthesis -> recurse. ``provider`` is…, RecursiveNicheDiscovery, _config(), _content(), _FakeTrendAdapter, _make_campaign(), _make_campaign_run() (+38 more)

### Community 21 - "LLMCallError"
Cohesion: 0.11
Nodes (19): LLMCallError, BaseException, RuntimeError, Typed failures raised by the LLM helper functions. The helpers used to swallow…, A single LLM call failed (transport, provider, or unparseable output)., Intelligence pipeline — orchestrates extraction and topic classification., classify_topics(), Any (+11 more)

### Community 22 - "AcquisitionCollector"
Cohesion: 0.16
Nodes (21): AcquisitionCollector, AsyncSession, Persists adapter output into ContentItem, AudienceInteraction, and Evidence…, _create_creator(), FakeAdapter, asyncio, AsyncSession, Integration tests for AcquisitionCollector against real Postgres. (+13 more)

### Community 23 - "Embedder"
Cohesion: 0.09
Nodes (23): AsyncSession, embed_texts(), embed_texts_async(), Embedder, ndarray, Protocol, Embedding generation for ProblemObservation text using sentence-transformers., Protocol for anything that can embed text into vectors. (+15 more)

### Community 24 - "Niche"
Cohesion: 0.08
Nodes (48): Base, generate_uuid(), TimestampMixin, CampaignNiche, How one niche performed within one campaign (§12). Never overwrites Niche's own…, Competitor, CompetitorType, An existing product/creator/workaround already serving a problem cluster's… (+40 more)

### Community 25 - "._persist_items"
Cohesion: 0.18
Nodes (7): _content_extra(), _int_or_none(), _is_interaction(), Any, Update the platform account's follower count and append a snapshot., Find the ContentItem a comment/reply/question/review belongs to., Whitelist adapter metadata that scoring or the dossier can use later.

### Community 27 - "MarketplaceAdapter"
Cohesion: 0.06
Nodes (42): _extract_price(), _html_to_text(), MarketplaceAdapter, _parse_etsy_listings(), _parse_gumroad_listings(), _parse_udemy_response(), Any, AsyncClient (+34 more)

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

### Community 34 - "schemas/dossier.py"
Cohesion: 0.12
Nodes (29): get_dossier_json(), CompetitorResponse, BaseModel, DataCoverageResponse, DossierCreatorResponse, DossierOpportunityResponse, DossierPlatformAccountResponse, DossierResponse (+21 more)

### Community 35 - "build_provider"
Cohesion: 0.09
Nodes (45): build_provider(), ProviderConfigError, Exception, No usable LLM provider is configured., Return the LLMProvider selected by configuration., FairUnavailableError, Exception, FAIR cannot be used in this process (not installed, or no provider key). (+37 more)

### Community 36 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 37 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 38 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 72 - "ResearchRun"
Cohesion: 0.07
Nodes (52): _mark_orphaned_runs(), Mark ResearchRun rows stuck in 'running' as 'failed' on startup., _latest_failed_rescans(), R12d: the newest failed ``watch_rescan`` run per targeted dossier (either…, str, Stored as plain strings on ResearchRun.status., What kind of research this run is (§11), distinct from RunScope, which…, ResearchRun (+44 more)

### Community 73 - "run.py"
Cohesion: 0.14
Nodes (27): Any, Production embedder using sentence-transformers (local, free)., SentenceTransformerEmbedder, CandidateConfig, _close(), main(), Run a pipeline from the command line using the configured provider/adapter.…, _run_add_campaign() (+19 more)

### Community 75 - "WarmStore"
Cohesion: 0.14
Nodes (13): SQLite table definitions for the CORP warm store. Mirrors the PostgreSQL…, _prep(), Any, WarmStore — async SQLite store for bulk CORP data. Provides idempotent put/get…, Serialize JSON-typed values, datetime strings, and enum instances for SQLite., Async SQLite store for bulk CORP data (evidence, embeddings, content)., WarmStore, Table (+5 more)

### Community 76 - "AmazonReviewAdapter"
Cohesion: 0.05
Nodes (46): AmazonReviewAdapter, _extract_asins(), _html_to_text(), _parse_review_date(), _parse_reviews(), AsyncClient, datetime, HTMLParser (+38 more)

### Community 77 - "CreatorOnboarder"
Cohesion: 0.09
Nodes (43): CreatorOnboarder, _is_enrichable_channel_id(), OnboardConfig, Any, AsyncSession, Search a niche and return every unique channel (no band filter, no cap).…, One deduplicated, batched subscriber-count lookup for the whole run., Only real YouTube channel IDs (``UC`` + 22 chars) can be looked up via the Data… (+35 more)

### Community 78 - "PatreonSubstackAdapter"
Cohesion: 0.06
Nodes (40): _extract_tiers(), _parse_substack_date(), _parse_substack_response(), PatreonSubstackAdapter, Any, AsyncClient, datetime, retry (+32 more)

### Community 79 - "test_coerce.py"
Cohesion: 0.10
Nodes (32): as_bool(), as_float(), as_int(), Any, Defensive coercion of untrusted LLM JSON values. Model output is not shape-…, Coerce ``value`` to float, returning ``default`` if it isn't numeric., Coerce ``value`` to int, returning ``default`` if it isn't a whole number.…, Coerce ``value`` to bool, treating the string "false"/"0"/"no"/… as False.… (+24 more)

### Community 80 - "AppStoreAdapter"
Cohesion: 0.07
Nodes (35): AppStoreAdapter, _parse_iso(), _parse_review_feed(), Any, AsyncClient, datetime, retry, Parse an Apple RSS ``updated`` timestamp (ISO 8601), normalized to UTC. (+27 more)

### Community 81 - "test_stackexchange_adapter.py"
Cohesion: 0.18
Nodes (25): _answer(), _make_response(), mock_client(), _mock_resp(), fixture, _question(), Tests for the Stack Exchange adapter — all HTTP calls mocked., A single record missing its id (e.g. deleted content omitted under… (+17 more)

### Community 82 - "EvidenceType"
Cohesion: 0.06
Nodes (49): EvidenceType, infer_evidence_type(), Which capability-provider interface (CORP1 Stage 4) produced this row. NOT NULL…, Lenient platform → evidence-type lookup; write paths use the strict…, Strict form for write paths: an unmapped platform is a configuration error and…, require_evidence_type(), DissatisfactionProvider, EvidenceProvider (+41 more)

### Community 83 - "ProviderExhaustedError"
Cohesion: 0.16
Nodes (28): ProviderExhaustedError, A quota that will not clear inside one call's retry window. ``retry_after`` is…, Clock, daily(), Fake, _pool(), Unit tests for the provider pool — scripted fake providers, fake clock., A provider that burns minutes timing out must not reset the cap. Before: the… (+20 more)

### Community 84 - "test_watch_rescanner.py"
Cohesion: 0.11
Nodes (45): DossierStatus, str, Denormalized mirror of the latest HumanDecision for fast dashboard queries.…, RuntimeError, A stage of the re-research chain failed; the message names it., RescanError, _d(), EvidenceAddingDriller (+37 more)

### Community 85 - "CrowdfundingAdapter"
Cohesion: 0.08
Nodes (31): CrowdfundingAdapter, _parse_indiegogo_date(), _parse_indiegogo_response(), _parse_kickstarter_response(), Any, AsyncClient, datetime, retry (+23 more)

### Community 86 - "GoogleTrendsAdapter"
Cohesion: 0.07
Nodes (31): GoogleTrendsAdapter, _has_pytrends(), _parse_rss_date(), _parse_trends_rss(), AsyncClient, datetime, retry, TrendProvider (CORP1 Stage 4/5, T2): delegates to collect() unchanged. (+23 more)

### Community 87 - "WikipediaAdapter"
Cohesion: 0.08
Nodes (27): Any, AsyncClient, retry, TrendProvider (CORP1 Stage 4/5, T2): sustained article pageviews are a demand-…, Collects Wikipedia article summaries with pageview trend data. Each article…, WikipediaAdapter, mock_client(), _mock_resp() (+19 more)

### Community 88 - "Creator"
Cohesion: 0.15
Nodes (34): archive_creator(), _as_utc(), generate_persisted_dossier(), _generate_product_ideas_best_effort(), get_campaign(), get_competitors(), get_creator(), get_dossier() (+26 more)

### Community 89 - "test_registry_rescan.py"
Cohesion: 0.14
Nodes (53): Dossier, One decision-ready dossier for one creator x niche x opportunity., _campaign_for_niche(), find_due_watched_dossiers(), AsyncSession, datetime, Registry Re-scan Scheduler (CORP1 Stage 5, T10). Architecture invariant (Stage…, Every currently-active (never-superseded) WATCHING dossier whose niche's… (+45 more)

### Community 90 - "test_dossier_decision_endpoint.py"
Cohesion: 0.14
Nodes (41): _make_client(), AsyncClient, asyncio, AsyncSession, LogCaptureFixture, parametrize, API tests for the dossier-level four-state decision gate (CORP1 Stage 5, T8):…, Two decisions on the same dossier must produce two rows, never an update to the… (+33 more)

### Community 91 - "test_web_adapter.py"
Cohesion: 0.07
Nodes (31): AsyncNetworkStream, is_public_url(), parse_page(), Any, HTMLParser, Extract title, description, visible text, and classified outbound links., All addresses ``host`` resolves to. Module-level so tests can stub it., Network backend that validates DNS at connection time. The pre-flight… (+23 more)

### Community 92 - "routes_ops.py"
Cohesion: 0.09
Nodes (42): BackgroundTasks, add_account(), CampaignPipelineRequest, ClusterDetail, create_campaign(), create_creator(), CreatorCreateRequest, discovery_status() (+34 more)

### Community 93 - "YtDlpAdapter"
Cohesion: 0.06
Nodes (34): _default_factory(), _Extractor, _host_allowed(), Any, datetime, Protocol, yt-dlp's native search syntax: ``ytsearch5:query``, ``ytsearchdate3:query``. A…, The slice of ``yt_dlp.YoutubeDL`` this adapter uses. (+26 more)

### Community 94 - ".select"
Cohesion: 0.08
Nodes (22): ColumnElement, _comparable_products(), DataCoverage, DossierData, DossierGenerator, OpportunityContext, Any, datetime (+14 more)

### Community 95 - "SearchDemandAdapter"
Cohesion: 0.08
Nodes (28): Any, AsyncClient, retry, SearchIntentProvider (CORP1 Stage 4/5, T2): autocomplete suggestions reveal…, Collects Google autocomplete suggestions as search-demand signals. Each…, SearchDemandAdapter, Evidence that people actively look for answers (autocomplete, "people also…, SearchIntentProvider (+20 more)

### Community 96 - "SourceHealthTracker"
Cohesion: 0.08
Nodes (24): AsyncSession, Any, BaseException, Path, Source health tracker — circuit breaker for tolerated adapters. Tracks per-…, Tracks adapter health and implements circuit-breaker logic. Usage:: tracker =…, SourceHealthRecord, SourceHealthTracker (+16 more)

### Community 97 - "HackerNewsAdapter"
Cohesion: 0.09
Nodes (25): HackerNewsAdapter, _parse_ts(), Any, AsyncClient, datetime, retry, Collects stories and comments from Hacker News via Algolia API. Stories become…, ProblemProvider (CORP1 Stage 4/5, T2): delegates to collect() unchanged —… (+17 more)

### Community 98 - "test_corp2_export.py"
Cohesion: 0.14
Nodes (38): DossierEvidence, One evidence row's membership in one dossier's CORP2 handoff trail. Mirrors…, HumanDecision, Append-only. Every decision is a new row — never update or delete., build_handoff_package(), EvidenceTrailEntry, HandoffPackage, _isoformat_nested() (+30 more)

### Community 99 - "register_error_handlers"
Cohesion: 0.09
Nodes (30): _body(), Any, FastAPI, One error shape for the UI to branch on. Every error body carries ``detail``…, register_error_handlers(), _adapter(), _http(), _integrity() (+22 more)

### Community 100 - "._score_opportunity"
Cohesion: 0.10
Nodes (28): growth_ratio(), Evidence depth input: observation counts weighted by how they were obtained., Relative growth between two snapshot values; None when not measurable., 0.5 = flat or unknown; strong growth → 1.0; decline → toward 0., Higher = less saturated = more room for a new product. ``commerce_overlap`` is…, How much the creator already talks about this problem in their own content., Fraction of the creator's audience platforms where the problem shows up.…, score_competition_saturation() (+20 more)

### Community 101 - "test_runs.py"
Cohesion: 0.15
Nodes (17): Advance the creator to ``working`` for the block, then ``done`` on success. The…, stage(), FakeSession, FakeSessionWithCreator, parametrize, Unit tests for the shared run lifecycle helpers — no database., A fully failed run is still research memory: it must come back to the caller…, test_finish_run_all_failed_returns_failed_run_without_raising() (+9 more)

### Community 102 - "app.py"
Cohesion: 0.07
Nodes (38): _close_quietly(), _discovery_busy(), DiscoveryProviders, _job_busy(), lifespan(), _noop_close(), AsyncSession, FastAPI (+30 more)

### Community 103 - "test_ops_no_db.py"
Cohesion: 0.07
Nodes (19): JobRegistry, JobResponse, JobStatus, BaseModel, str, The in-flight job of a given kind, if any. Campaign-less jobs (an autonomous…, Run ``work`` and record its outcome on ``job``. Never raises., Mark any still-running jobs as failed (called at shutdown). (+11 more)

### Community 104 - "test_niche_candidates.py"
Cohesion: 0.21
Nodes (22): NicheCandidateGenerator, _candidates(), FakeEmbedder, NamingProvider, asyncio, AsyncSession, ndarray, Integration tests for NicheCandidateGenerator against real Postgres. (+14 more)

### Community 105 - "test_discovery.py"
Cohesion: 0.18
Nodes (24): NicheDiscoveryCollector, AsyncSession, skipif, _campaign(), FakeAdapter, asyncio, AsyncSession, Path (+16 more)

### Community 106 - "CampaignResearchBatch"
Cohesion: 0.09
Nodes (42): BatchConfig, CampaignResearchBatch, CreatorResearcher, AsyncSession, Protocol, ResearchReport, T, _FakeReport (+34 more)

### Community 107 - "App.tsx"
Cohesion: 0.14
Nodes (23): react-router-dom, useCampaigns(), useCreateCampaign(), useJobs(), useResearchRuns(), useWatchingDossiers(), LastRescan, Layout() (+15 more)

### Community 108 - "CreatorDetailPage.tsx"
Cohesion: 0.09
Nodes (24): useArchiveCreator(), useClusterObservations(), useClusters(), useCreator(), useDecisions(), useDossier(), useGeneratePersistedDossier(), usePersistedDossier() (+16 more)

### Community 109 - "EcosystemEstimator"
Cohesion: 0.21
Nodes (24): EcoConfig, EcosystemEstimator, AsyncSession, FakeEnricher, _FakeItem, FakeSearchAdapter, asyncio, AsyncSession (+16 more)

### Community 110 - "test_provider_health.py"
Cohesion: 0.07
Nodes (23): PingResult, Real end-to-end liveness probe: enumerate providers, then run a trivial schema-…, Outcome of a FAIR end-to-end liveness probe. ``ok`` is only true when at least…, client(), _FakeFair, fixture, Tests for /providers/health — the endpoint that reports the active LLM provider…, A bare Gemini/Groq or a PooledProvider isn't a FairProvider — no ping is run,… (+15 more)

### Community 111 - "test_product_ideation.py"
Cohesion: 0.25
Nodes (22): ProductIdea, One LLM-generated, evidence-grounded product idea for one creator's problem…, IdeationConfig, ProductIdeationGenerator, AsyncSession, _config(), _idea(), _make_cluster_with_evidence() (+14 more)

### Community 112 - "hooks.ts"
Cohesion: 0.10
Nodes (29): api, Campaign, CampaignCreateInput, CampaignNiche, CampaignNicheStatus, CampaignStatus, CommercialSignal, CompetitorStrength (+21 more)

### Community 113 - "EvidenceOrigin"
Cohesion: 0.22
Nodes (26): EvidenceOrigin, Whether the row is raw data or an LLM-derived claim (Provenance Invariant). NOT…, _create_candidate(), _create_dossier_prereqs(), asyncio, AsyncSession, parametrize, Integration tests for CORP1 Stage 4 / T0: the niche + niche-candidate drill-… (+18 more)

### Community 114 - "NormalizedContent"
Cohesion: 0.06
Nodes (21): NormalizedContent, BaseModel, The one schema every adapter family emits. This is the Build item.…, Any, AsyncClient, datetime, retry, Newest posts for ``r/<sub>``, ``u/<user>`` or a bare subreddit name. (+13 more)

### Community 115 - "scoring/niche_qualification.py"
Cohesion: 0.15
Nodes (26): compute_components(), compute_confidence(), compute_qualification_score(), compute_research_completeness(), load_rules(), _log_score(), NicheInput, Any (+18 more)

### Community 116 - "test_dossier_persistence.py"
Cohesion: 0.29
Nodes (28): _make_creator(), _make_evidence(), _make_niche(), _make_run(), _make_scored_opportunity(), _niche_evidence(), _promoted_candidate(), asyncio (+20 more)

### Community 117 - "require_api_key"
Cohesion: 0.24
Nodes (10): Single shared API key. Enough for a one-team console; swap for real auth later., No-op when API_KEY is unset (local dev); otherwise the header must match., require_api_key(), No-DB tests for the shared API-key dependency., Starlette decodes headers as latin-1; non-ASCII chars must not cause a…, test_matching_key_passes(), test_missing_key_rejected(), test_no_key_configured_is_noop() (+2 more)

### Community 118 - "record_query"
Cohesion: 0.13
Nodes (28): str, One executed search, recorded under its ResearchRun (§12, ADR-006). This is the…, ResearchQuery, ResearchQueryStatus, find_queries(), AsyncSession, datetime, Research query ledger — the persistence service for ResearchQuery (§13). Two… (+20 more)

### Community 119 - "test_niche_naming.py"
Cohesion: 0.14
Nodes (25): check_grounding(), ClusterName, name_cluster(), _normalize(), Name an evidence cluster as a niche candidate (Slice 8, §16). The LLM's role…, Ask the provider to name a cluster; verify every cited term against the texts.…, Return the cited terms that do NOT occur in the texts (case/space-insensitive).…, _answer() (+17 more)

### Community 120 - "test_groq_provider.py"
Cohesion: 0.19
Nodes (26): _capture(), handler(), _completion(), _provider(), Unit tests for the Groq provider — HTTP mocked, no network., A long retry-after is passed through for the pool to judge; it is not a daily…, The contract is a JSON object; a top-level list must not leak through., Non-reasoning models reject the parameter, so None/"" must not send it. (+18 more)

### Community 121 - "test_multi_discovery.py"
Cohesion: 0.10
Nodes (21): _to_evidence(), FakeAdapter, _make_item(), mock_session(), Exception, fixture, patch, Path (+13 more)

### Community 122 - "NicheLifecycleStatus"
Cohesion: 0.27
Nodes (20): NicheCandidateEvidence, One evidence row's membership in one candidate, with its similarity to the…, NicheLifecycleStatus, The cycle from §7: CANDIDATE precedes verification; ACTIVE/EXPAND then cycle…, NicheVerifier, AsyncSession, VerifyConfig, VerifyResult (+12 more)

### Community 123 - "ProblemCluster"
Cohesion: 0.14
Nodes (19): ProblemCluster, ClusterContext, CreatorContext, Frequency of the most recent superseded cluster with the same label., Everything about a creator the per-cluster scoring needs, loaded once., _creator_context(), FakeSession, _make_pipe_and_helpers() (+11 more)

### Community 124 - "package.json"
Cohesion: 0.08
Nodes (24): oxlint, react-dom, tailwindcss, @tailwindcss/vite, @types/node, @types/react, @types/react-dom, typescript (+16 more)

### Community 125 - "test_niche_canonicalization.py"
Cohesion: 0.12
Nodes (44): NicheCandidateStatus, str, NicheAlias, Alternate wording that resolves to one canonical Niche. Existence of this table…, CanonConfig, NicheCanonicalizer, AsyncSession, The Niche the parent candidate resolved to (PROMOTED or MERGED -- lineage… (+36 more)

### Community 126 - "providers/registry.py"
Cohesion: 0.08
Nodes (28): ProviderError, ProviderUnavailableError, Exception, Provider health signals the pool acts on. Only these two trigger failover.…, Transient failure (5xx, timeout, transport) that outlasted the retry budget., Any, Map a non-accepted SolveResponse onto the pool's error vocabulary., Fold ``system`` into the single task string FAIR's ``solve()`` accepts. FAIR… (+20 more)

### Community 127 - "Campaign"
Cohesion: 0.31
Nodes (22): Campaign, CampaignNicheStatus, str, How far this niche has gotten within this specific campaign. Distinct from…, The top-level research execution unit above niche and creator research. A…, NicheSelector, AsyncSession, SelectionConfig (+14 more)

### Community 128 - "MultiSourceDiscovery"
Cohesion: 0.17
Nodes (8): Write the raw normalized items as JSONL; return a data-path-relative reference.…, MultiSourceDiscovery, Any, Orchestrates niche discovery across multiple adapters. Usage:: disco =…, Fan out ``query`` across all healthy niche adapters under ``campaign_id``.…, Shared filename-safe slug helper for acquisition warmstore paths., slugify(), test_discover_unknown_campaign()

### Community 129 - "test_captions.py"
Cohesion: 0.16
Nodes (21): fetch_youtube_caption(), Any, Group raw snippets into segments split at natural pauses. A new segment starts…, Return the transcript as a ``caption`` item, or None when unavailable.…, _segment_snippets(), TranscriptSegment, _mock_fetched_transcript(), Tests for YouTube transcript segmentation and fetch. (+13 more)

### Community 130 - "ResearchOrchestrator"
Cohesion: 0.15
Nodes (14): AsyncSession, Keep the failed run row a crashing stage flushed. If the session is poisoned…, ResearchOrchestrator, ResearchReport, _fake_session(), _FakeCreator, _orchestrator(), patch (+6 more)

### Community 131 - "RegistryRescanScheduler"
Cohesion: 0.18
Nodes (7): BusyCheck, async_sessionmaker, Protocol, True when a job is already queued/running for this dossier's campaign (``None``…, The in-process scheduled job itself: an asyncio loop ticking every…, RegistryRescanScheduler, RescannerFactory

### Community 132 - "test_campaign_endpoints.py"
Cohesion: 0.29
Nodes (22): _make_client(), AsyncClient, asyncio, AsyncSession, API endpoint tests for campaign read (Slice 16) and write (Slice 17)., CORP1 Stage 5, T4: discover no longer needs a platform -- the recursive…, _seed_campaign_with_niches(), test_campaign_pipeline_conflict() (+14 more)

### Community 133 - "test_reddit_adapter.py"
Cohesion: 0.21
Nodes (20): _adapter(), handler(), _comment(), _listing(), _post(), Unit tests for the Reddit adapter — public JSON endpoints mocked, no network., A single malformed record (e.g. a promoted/placeholder child with no id) must…, Build an adapter whose HTTP client answers from a path→body table. (+12 more)

### Community 134 - "CompetitivePipeline"
Cohesion: 0.21
Nodes (8): CompetitivePipeline, _http_url_or_none(), Keep only http(s) URLs: the dossier renders ``Competitor.url`` into an href., Discovers competitors for each ProblemCluster via LLM analysis., Run competitive discovery for all clusters belonging to a creator., parametrize, test_http_url_or_none(), test_http_url_or_none_truncates_to_column_width()

### Community 135 - "CampaignDetailPage.tsx"
Cohesion: 0.12
Nodes (15): react, @tanstack/react-query, useCampaign(), useCampaignCreators(), useCampaignNiches(), useJob(), useStartCampaignPipeline(), App() (+7 more)

### Community 136 - "matched_exclusion"
Cohesion: 0.12
Nodes (13): _evidence_supporting(), matched_exclusion(), _normalize(), Deterministic substring match against Stage 3's exclusion categories. Returns…, Full-text (untruncated) superset match: every row whose raw_text contains at…, RuntimeError, Return up to ``limit`` topics ready to drill, best first., Best-effort Google Trends score per topic. Missing keys mean no signal, which… (+5 more)

### Community 137 - "3. Product specification (Stage 3 — to freeze)"
Cohesion: 0.10
Nodes (20): 1. Problem (Stage 1/2 recap), 2. What exists to build on (Stage 2 research, verified in code), 3.1 Watch re-scan (R12), 3.2 Research More completion (R12a — same machinery, do first), 3.3 "The evidence strengthened" — definition (decision needed), 3.4 Cost and safety limits (decision needed), 3.5 Human-visible behaviour, 3.6 Non-goals (+12 more)

### Community 138 - "ScriptedProvider"
Cohesion: 0.13
Nodes (7): FakeResearcher, FakeYouTubeSearchAdapter, Any, Synthesizes exactly one specific-enough niche, grounded in the fake evidence's…, Returns one channel per niche query, with a follower count inside the default…, Matches the CreatorResearcher Protocol CampaignResearchBatch accepts --…, ScriptedProvider

### Community 139 - ".generate"
Cohesion: 0.15
Nodes (14): InvalidResearchRunError, Exception, validate_run_type(), _cosine(), Any, ndarray, Every non-empty evidence row collected by this campaign's discovery runs., Group the campaign's discovery evidence into staged candidates. Returns the run. (+6 more)

### Community 140 - "compute_score"
Cohesion: 0.18
Nodes (14): compute_hash(), compute_score(), Weighted mean of the components actually supplied. Normalise over the weight…, Deterministic hash: same inputs → same hash. Adapted from CIP Step 9., test_compute_hash_changes_with_input(), test_compute_hash_changes_with_rule_version(), test_compute_hash_deterministic(), test_compute_score_weighted_average() (+6 more)

### Community 141 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+11 more)

### Community 142 - "NicheQualifier"
Cohesion: 0.32
Nodes (17): NicheQualifier, asyncio, AsyncSession, Integration tests for NicheQualifier against real Postgres., A verified niche without a promoted candidate still gets scored with zero…, Same inputs produce the same score on repeated runs., _setup_verified_niche(), test_broad_domain_penalised() (+9 more)

### Community 143 - "PruneService"
Cohesion: 0.18
Nodes (14): PruneReport, PruneService, Any, AsyncSession, Maintenance ops — prune bulk history from Postgres to keep it bounded. The warm…, Deletes safe-to-drop bulk history older than a retention window. Dry-run by…, No-DB unit tests for the prune maintenance service., _session() (+6 more)

### Community 144 - "DecisionType"
Cohesion: 0.21
Nodes (16): create_decision(), DossierDecisionRequest, DossierDecisionResponse, The four-state dossier decision gate: Reject / Research More / Watch / Approve,…, record_dossier_decision(), DecisionType, Gate, DecisionCreate (+8 more)

### Community 145 - "build_adapter"
Cohesion: 0.09
Nodes (14): build_adapter(), Adapter selection — builds a SourceAdapter for a platform name from settings., _normalize(), AsyncClient, Collects a creator's landing page and its commerce-related outbound pages., GET ``url`` following redirects by hand so each hop is host-checked. Returns…, Stable id for a page: scheme+host+path, no query/fragment, max 255 chars., WebPresenceAdapter (+6 more)

### Community 146 - "Ideator"
Cohesion: 0.29
Nodes (5): CreatorResearcher, Ideator, NicheDriller, Protocol, StageReport

### Community 147 - "compilerOptions"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 148 - "test_discovery_scan.py"
Cohesion: 0.10
Nodes (31): Why a pass returned what it did — surfaced in the run record so a scan that…, A broad topic cleared to enter recursive discovery., SeedTopic, TrendScanStats, DiscoveryPassStats, get_or_create_autonomous_campaign(), Any, The autonomous discovery crawler — CORP1 Step 1 with no user input. One pass… (+23 more)

### Community 149 - "ProblemObservation"
Cohesion: 0.12
Nodes (18): ProblemObservation, ClusterPipeline, _cosine_to_centroid(), ndarray, Clustering pipeline — embed observations, cluster, persist to DB, unify topics., Merge cluster labels into the creator's ContentItem.topics list. Produces a…, Cosine similarity of each row to the centroid, in [0, 1] (clipped)., Embeds ProblemObservations, clusters them, and persists results. A new run for… (+10 more)

### Community 150 - "NichePolicyClass"
Cohesion: 0.23
Nodes (13): NichePolicyClass, str, Configuration-driven policy tier (ADR-008); classification rules live outside…, CampaignNicheCreate, CampaignNicheDetailResponse, CampaignNicheResponse, BaseModel, NicheAliasCreate (+5 more)

### Community 151 - "product_ideation.py"
Cohesion: 0.14
Nodes (19): ProductIdeaComplexity, ProductIdeaType, str, Matches the CORP1 spec's product-idea vocabulary (Stage 1, step 6)., _as_price(), _evidence_supporting(), _normalize(), propose_ideas() (+11 more)

### Community 152 - "Decisions"
Cohesion: 0.13
Nodes (14): 1. Exclusion uses `NicheCandidateStatus.REJECTED`, not `policy_class`, 2. Only `AdapterFamily.NICHE` adapters fan out for topic queries, 3. Registry check: exact match against `Niche`/`NicheAlias`, 4. Multi-capability duplicate evidence: intentional two-lens persistence, 5. Evidence pool includes pre-existing rows, not just newly-inserted ones, 6. LLM provider is required, not optional, 7. Ungrounded synthesized niches are dropped, never given a fallback name, ADR-0033 — CORP1 Stage 5, T3: Recursive Niche Discovery Engine (+6 more)

### Community 153 - "ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator"
Cohesion: 0.13
Nodes (14): ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator, Consequences, Context, Decisions, Evidence trail respects the Stage 4 acceptance test directly, Files changed, `generate_and_persist` is additive, not a replacement, `niche_id` comes from the caller, not auto-derived inside the generator (+6 more)

### Community 154 - "_seed_full"
Cohesion: 0.31
Nodes (13): asyncio, AsyncSession, _load_observations caps at 10 rows; with no ORDER BY which 10 of N came back…, Seed a creator with clusters, signals, and scores — full pipeline output., _seed_full(), test_dossier_contains_competitors(), test_dossier_contains_evidence(), test_dossier_contains_scores() (+5 more)

### Community 155 - "ADR-0040 — CORP1 Stage 5, T10: Registry Re-scan Scheduler"
Cohesion: 0.14
Nodes (13): ADR-0040 — CORP1 Stage 5, T10: Registry Re-scan Scheduler, Closing the loop: advancing `Niche.next_recheck_at`, Consequences, Context, Decisions, Files changed, No `ResearchRun` created for a re-scan pass, Note on unrelated working-tree state (+5 more)

### Community 156 - "ADR-0034 — CORP1 Stage 5, T4: Campaign Pipeline Rewire"
Cohesion: 0.15
Nodes (12): ADR-0034 — CORP1 Stage 5, T4: Campaign Pipeline Rewire, Consequences, Context, Decisions, `discover` now calls `RecursiveNicheDiscovery`, and no longer needs a platform, Files changed, Note on unrelated working-tree state (per Stage 8 review), Scope had to expand by one file beyond the frozen list: `corp/api/routes_ops.py` (+4 more)

### Community 157 - "ADR-0042 — CORP1 Stage 5, T13: Kickstarter + Indiegogo Adapter (Phase 2.3)"
Cohesion: 0.15
Nodes (12): ADR-0042 — CORP1 Stage 5, T13: Kickstarter + Indiegogo Adapter (Phase 2.3), Comments/community engagement: not implemented, disclosed, Consequences, Context, Decisions, Files changed, Indiegogo: `POST /api/projectSearch/searchProjects`, Kickstarter: `GET /discover/advanced.json` (+4 more)

### Community 158 - "test_creator_archive.py"
Cohesion: 0.40
Nodes (12): _make_client(), _make_creator(), AsyncClient, asyncio, AsyncSession, Archive/unarchive a creator (R14): a reversible "hide from the working list"…, Archiving must not interfere with the existing status/min_score filters., test_archive_hides_from_default_list_but_not_include_archived() (+4 more)

### Community 159 - "client.ts"
Cohesion: 0.35
Nodes (10): ApiError, getApiBase(), getApiKey(), request(), requestWithCount(), send(), setApiBase(), setApiKey() (+2 more)

### Community 160 - "ADR-0030 — CORP1 Stage 4, T0: Niche Drill-Down Tree + Dossier Model"
Cohesion: 0.17
Nodes (11): 1. Reuse, don't duplicate, existing exclusion machinery, 2. Niche and NicheCandidate: add a real tree, 3. Evidence: evidence_type only, not evidence_type + origin, 4. HumanDecision: RESEARCH_MORE + dossier_id, 5. New: Dossier + DossierEvidence, ADR-0030 — CORP1 Stage 4, T0: Niche Drill-Down Tree + Dossier Model, Consequences, Context (+3 more)

### Community 161 - "ADR-0032 — CORP1 Stage 5, T2: Wrap Existing Adapters"
Cohesion: 0.17
Nodes (11): ADR-0032 — CORP1 Stage 5, T2: Wrap Existing Adapters, Consequences, Context, Decision, Files changed, Gap found: Wikipedia was missing from the frozen mapping table, Known risk for T3 (flagged by Stage 8 review, not resolved here), No changes to `collect()` anywhere (+3 more)

### Community 162 - "ADR-0037 — CORP1 Stage 5, T7: Scoring Engine Update"
Cohesion: 0.17
Nodes (11): ADR-0037 — CORP1 Stage 5, T7: Scoring Engine Update, Confirmed backward-compatible with the unmodified live pipeline, Consequences, Context, Decisions, `engine.py` stays a pure scoring-math library — no DB, no pipeline call, Files changed, Four new functions, matched to Stage 4's capability-type mapping (+3 more)

### Community 163 - "ADR-0038 — CORP1 Stage 5, T8: Four-State Decision Gate"
Cohesion: 0.17
Nodes (11): ADR-0038 — CORP1 Stage 5, T8: Four-State Decision Gate, Consequences, Context, Decisions, Files changed, Frontend: `CreatorDetailPage.tsx` + two necessary companions, Note on unrelated working-tree state, Scope expansion: `corp/workers/intelligence/niche_discovery.py` (user-directed) (+3 more)

### Community 164 - "ADR-0039 — CORP1 Stage 5, T9: CORP2 Handoff Package"
Cohesion: 0.17
Nodes (11): A precise reading of the test requirement's wording, ADR-0039 — CORP1 Stage 5, T9: CORP2 Handoff Package, `build_handoff_package(session, dossier_id) -> HandoffPackage`, Consequences, Context, Decisions, Files changed, Not wired to T8's Approve path yet (+3 more)

### Community 165 - "ADR-0043 — CORP1 Stage 5, T14: Patreon + Substack Adapter (Phase 2.4)"
Cohesion: 0.17
Nodes (11): ADR-0043 — CORP1 Stage 5, T14: Patreon + Substack Adapter (Phase 2.4), Consequences, Context, Decisions, Files changed, Note on unrelated working-tree state, One adapter, umbrella platform name — mirrors `CrowdfundingAdapter`, Patreon: intentionally not implemented, not stubbed with a guess (+3 more)

### Community 166 - "ADR-0044 — CORP1 Stage 5, T21: Full Scoring Integration (Phase 3.6)"
Cohesion: 0.17
Nodes (11): ADR-0044 — CORP1 Stage 5, T21: Full Scoring Integration (Phase 3.6), Behavioral change: 10 → 14 components, Consequences, Context, Decisions, Evidence-type counts via Creator → CreatorNiche → niche ResearchRuns, Files changed, Graceful degradation when no niche evidence exists (+3 more)

### Community 167 - "ADR-0045 — Wire Registry Re-scan Scheduler into App Startup"
Cohesion: 0.17
Nodes (11): ADR-0045 — Wire Registry Re-scan Scheduler into App Startup, Consequences, Context, Decisions, Existing tests unaffected, FastAPI lifespan context manager, Files changed, Graceful degradation on construction failure (+3 more)

### Community 168 - "Running CORP locally (laptop + flash drive)"
Cohesion: 0.17
Nodes (12): 1. Install dependencies, 2. Set up PostgreSQL + pgvector, 3. Configure `.env`, 4. Run migrations, 5. Run the app, Common commands, Flash-drive notes, How the hot/warm split actually works (+4 more)

### Community 169 - "test_handoff_endpoint.py"
Cohesion: 0.10
Nodes (26): _engine(), get_session(), _LazySessionmaker, _make_session_factory(), async_sessionmaker, AsyncEngine, AsyncSession, Proxy that creates the real async_sessionmaker on first use. (+18 more)

### Community 170 - "Slice 7 — Niche Discovery Light: One Source"
Cohesion: 0.18
Nodes (10): 1. Reddit's unauthenticated `.json` feed is blocked (external), 2. A failed search was persisted and then rolled back (mine), 3. The live approved source is YouTube search, via a small adapter enablement, Assumptions, Lesson reused, Live verification (real dev database, real source), Open items / risks, Problems found during this slice (+2 more)

### Community 171 - "ADR-0031 — CORP1 Stage 5, T1: Capability-Provider Interfaces"
Cohesion: 0.18
Nodes (10): ADR-0031 — CORP1 Stage 5, T1: Capability-Provider Interfaces, `CAPABILITY_INTERFACES` convenience tuple, Consequences, Context, Decision, EvidenceProvider declares `evidence_type` as an unset ClassVar, Files changed, Known risk for T2/T3 (flagged by Stage 8 review, not resolved here) (+2 more)

### Community 172 - "ADR-0035 — CORP1 Stage 5, T5: Product Idea Generation"
Cohesion: 0.18
Nodes (10): ADR-0035 — CORP1 Stage 5, T5: Product Idea Generation, Consequences, Context, Corrected acceptance criterion: no `Evidence.origin` field exists, Decision, Evidence membership: full-text superset match, deduped by evidence id, Files changed, Grounding reuses `niche_naming.check_grounding` unchanged (+2 more)

### Community 173 - "YouTubeAPIEnricher"
Cohesion: 0.15
Nodes (9): _as_int_or_none(), NicheEcoResult, Any, Search one niche and return every unique channel, uncorrected subscriber counts…, One deduplicated, batched subscriber-count lookup for the whole campaign,…, yt-dlp counts are ints, but be defensive: a string would make the…, Fetches real subscriber counts via YouTube Data API v3. Costs 1 quota unit per…, YouTubeAPIEnricher (+1 more)

### Community 174 - "_days_from_recency"
Cohesion: 0.29
Nodes (9): _days_from_recency(), Invert clustering.py's exponential decay (recency = exp(-days/365)) back to an…, Unit tests for scoring_pipeline._days_from_recency — no DB required., clustering.py reserves exactly 0.0 for "no timestamp data at all" — must not be…, The bug this guards against: a 400-day-old cluster and a 4000-day-old cluster…, test_different_old_ages_stay_distinguishable(), test_inverts_clustering_exponential_decay(), test_recency_one_is_zero_days() (+1 more)

### Community 175 - "Slice 19 — WarmStore Foundation"
Cohesion: 0.20
Nodes (9): Acceptance criteria and how each is met, Assumptions, CLI, Config, Dependency, New package: `corp/warmstore/`, Slice 19 — WarmStore Foundation, Verification (+1 more)

### Community 176 - "ADR-0046 — Wire T9 Handoff to T8's Approve Decision Path"
Cohesion: 0.20
Nodes (9): ADR-0046 — Wire T9 Handoff to T8's Approve Decision Path, Consequences, Context, Decisions, Files changed, Note on unrelated working-tree state, Pull endpoint, not eager computation, Stale comment removed (+1 more)

### Community 177 - "ADR-0047 — Fix DossierGenerator Cross-Niche Opportunity Mismatch"
Cohesion: 0.20
Nodes (9): ADR-0047 — Fix DossierGenerator Cross-Niche Opportunity Mismatch, Consequences, Context, Decision, Evidence-chain filtering without schema changes, Files changed, Note on unrelated working-tree state, Verification (+1 more)

### Community 178 - "devDependencies"
Cohesion: 0.20
Nodes (10): devDependencies, oxlint, tailwindcss, @tailwindcss/vite, @types/node, @types/react, @types/react-dom, typescript (+2 more)

### Community 179 - "CreatorsPage.tsx"
Cohesion: 0.27
Nodes (6): useArchivedCreators(), useCreateCreator(), useCreators(), PlatformAccountCreateInput, AddCreatorForm(), CreatorsPage()

### Community 180 - "test_intelligence_pipeline.py"
Cohesion: 0.14
Nodes (23): ContentType, InteractionType, str, ContentItemCreate, ContentItemResponse, InteractionCreate, InteractionResponse, BaseModel (+15 more)

### Community 181 - "decide_resurface"
Cohesion: 0.29
Nodes (6): decide_resurface(), Design §3.3 option C. Pure so it can be unit-tested exhaustively., ResurfaceDecision, _Outcome, Commits an early stage, then hits a real DB error and rolls the shared session…, RollbackRescanner

### Community 182 - "Slice 18 — Creator Intelligence Dashboard"
Cohesion: 0.22
Nodes (8): Acceptance criteria and how each is met, Assumptions, Implementation, New sections on CreatorDetailPage, Slice 18 — Creator Intelligence Dashboard, Status badge colors, Verification, What shipped

### Community 183 - "Slice 20 — WarmStore Pipeline Integration"
Cohesion: 0.22
Nodes (8): Acceptance criteria and how each is met, Assumptions, Modified pipelines, New module: `corp/warmstore/sync.py`, Pattern, Slice 20 — WarmStore Pipeline Integration, Verification, What shipped

### Community 184 - "Slice 21 — YouTube Transcript Segmentation"
Cohesion: 0.22
Nodes (8): Acceptance criteria and how each is met, Assumptions, Backward compatibility, Changes to `corp/workers/adapters/captions.py`, Slice 21 — YouTube Transcript Segmentation, Tests, Verification, What shipped

### Community 185 - "Decision"
Cohesion: 0.22
Nodes (8): 1. SearchDemandAdapter, 2. AmazonReviewAdapter, ADR-0026 — Slice 23: Niche-Signal Adapters (Search Demand + Amazon Reviews), Consequences, Context, Decision, Files changed, Key design choices

### Community 186 - "Decision"
Cohesion: 0.22
Nodes (8): 1. Source Health Tracker (`corp/workers/adapters/health.py`), 2. Multi-Source Niche Discovery (`corp/workers/acquisition/multi_discovery.py`), ADR-0029 — Slice 26: Multi-Source Niche Discovery + Source Health Tracking, Consequences, Context, Decision, Files changed, Key design choices

### Community 187 - "ADR-0059 — R11b: yt-dlp type stubs; triage of the five "pre-existing" test failures"
Cohesion: 0.22
Nodes (8): ADR-0059 — R11b: yt-dlp type stubs; triage of the five "pre-existing" test failures, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Triage of the five, Verification

### Community 188 - "CORP — Creator Opportunity Research Platform"
Cohesion: 0.22
Nodes (5): Architecture & decisions, CORP — Creator Opportunity Research Platform, Development, Getting started, What's in the box

### Community 189 - "Slice 17 — Campaign Pipeline API + Campaign Dashboard UI"
Cohesion: 0.25
Nodes (7): Acceptance criteria and how each is met, Assumptions and open items, Backend, Frontend, Slice 17 — Campaign Pipeline API + Campaign Dashboard UI, Verification, What shipped

### Community 190 - "ADR-0028 — Slice 25: Remaining Licensed/Tolerated Niche-Signal Adapters"
Cohesion: 0.25
Nodes (7): ADR-0028 — Slice 25: Remaining Licensed/Tolerated Niche-Signal Adapters, Consequences, Context, Decision, Files changed, Key design choices, New adapters

### Community 191 - "ADR-0048 — R1: Evidence-type fallback mapping keyed on real adapter platform strings"
Cohesion: 0.25
Nodes (7): ADR-0048 — R1: Evidence-type fallback mapping keyed on real adapter platform strings, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 192 - "ADR-0049 — R2: LLM-derived Evidence rows carry `origin = INFERENCE`"
Cohesion: 0.25
Nodes (7): ADR-0049 — R2: LLM-derived Evidence rows carry `origin = INFERENCE`, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 193 - "ADR-0050 — R3: Backfill Evidence provenance and enforce it at the database"
Cohesion: 0.25
Nodes (7): ADR-0050 — R3: Backfill Evidence provenance and enforce it at the database, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 194 - "ADR-0051 — R6: Scope dossier demand validation to the niche's own evidence"
Cohesion: 0.25
Nodes (7): ADR-0051 — R6: Scope dossier demand validation to the niche's own evidence, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 195 - "ADR-0052 — R4: Carry drill lineage onto Niche.parent_niche_id / depth"
Cohesion: 0.25
Nodes (7): ADR-0052 — R4: Carry drill lineage onto Niche.parent_niche_id / depth, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 196 - "ADR-0053 — R5: Depth cap on research_more, full fan-out, registry clock at promotion, EXCLUDED lifecycle"
Cohesion: 0.25
Nodes (7): ADR-0053 — R5: Depth cap on research_more, full fan-out, registry clock at promotion, EXCLUDED lifecycle, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 197 - "ADR-0054 — R8: Re-scan scheduler — clock on success only, savepoint per dossier, resurface only on change"
Cohesion: 0.25
Nodes (7): ADR-0054 — R8: Re-scan scheduler — clock on success only, savepoint per dossier, resurface only on change, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 198 - "ADR-0055 — R9: Gate A returns 422 for an invalid decision or foreign opportunity score"
Cohesion: 0.25
Nodes (7): ADR-0055 — R9: Gate A returns 422 for an invalid decision or foreign opportunity score, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 199 - "ADR-0056 — R7: Surface the enriched dossier content in the UI and the HTML dossier"
Cohesion: 0.25
Nodes (7): ADR-0056 — R7: Surface the enriched dossier content in the UI and the HTML dossier, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 200 - "ADR-0057 — R10: Frontend/API correctness batch"
Cohesion: 0.25
Nodes (7): ADR-0057 — R10: Frontend/API correctness batch, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 201 - "ADR-0058 — R11: Project-wide static gates clean, model/migration defaults aligned"
Cohesion: 0.25
Nodes (7): ADR-0058 — R11: Project-wide static gates clean, model/migration defaults aligned, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 202 - "ADR-0060 — R12b: Creator.status mirrors the dossier decision gate"
Cohesion: 0.25
Nodes (7): ADR-0060 — R12b: Creator.status mirrors the dossier decision gate, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 203 - "ADR-0061 — R12a: Research More completes through a shared WatchRescanner; product ideation wired"
Cohesion: 0.25
Nodes (7): ADR-0061 — R12a: Research More completes through a shared WatchRescanner; product ideation wired, Consequences, Context, Decision, Files changed, Note on unrelated working-tree state, Verification

### Community 204 - "CORP1 Remediation Plan — Spec Alignment (September 2026)"
Cohesion: 0.25
Nodes (7): CORP1 Remediation Plan — Spec Alignment (September 2026), Deliberately out of scope, Phase A — Restore the Provenance Invariant, Phase B — Make the niche tree real, Phase C — Make the dossier truthful, Phase D — API/UI correctness and hygiene, Planned after this run (needs its own Stage 3/4 pass first)

### Community 205 - "Slice 3 — Campaign ↔ Niche Relationship"
Cohesion: 0.29
Nodes (6): Assumptions, Cascade-delete decision, Problems found during this slice, Slice 3 — Campaign ↔ Niche Relationship, Unresolved, pre-existing issues, What shipped

### Community 206 - "Slice 4 — Creator ↔ Niche Relationship"
Cohesion: 0.29
Nodes (6): Cascade decision, Compatibility verification, Problems found during this slice, Slice 4 — Creator ↔ Niche Relationship, Unresolved, pre-existing issues, What shipped

### Community 207 - "Slice 6 — Research Query Ledger"
Cohesion: 0.29
Nodes (6): Assumptions, Placement decision, Problem found and fixed during this slice, Slice 6 — Research Query Ledger, Unresolved, pre-existing issues, What shipped

### Community 208 - "Provider pool: Gemini daily cap + Groq failover"
Cohesion: 0.29
Nodes (6): Investigated and rejected, Open items, Problems found live, in order, and what each changed, Provider pool: Gemini daily cap + Groq failover, What shipped, What the live runs prove

### Community 209 - "FAIR as an in-process provider; prompts carry their answer schema"
Cohesion: 0.29
Nodes (6): FAIR as an in-process provider; prompts carry their answer schema, Install, Noted, Problems found by the first live run (#7) and fixed, Verification, What shipped

### Community 210 - "Slice 8 — Evidence → Candidate Niche"
Cohesion: 0.29
Nodes (6): Acceptance criteria → how each is met, Assumptions and open items, Problems found and fixed during this slice, Slice 8 — Evidence → Candidate Niche, Verification, What shipped

### Community 211 - "ADR-0025 — Slice 22: Stack Exchange Niche-Signal Adapter"
Cohesion: 0.29
Nodes (6): ADR-0025 — Slice 22: Stack Exchange Niche-Signal Adapter, Consequences, Context, Decision, Files changed, Key design choices

### Community 212 - "ADR-0027 — Slice 24: Marketplace Listings Adapter (Gumroad / Etsy / Udemy)"
Cohesion: 0.29
Nodes (6): ADR-0027 — Slice 24: Marketplace Listings Adapter (Gumroad / Etsy / Udemy), Consequences, Context, Decision, Files changed, Key design choices

### Community 213 - "ADR-0062 — R12c: the Watch re-scan scheduler re-researches through the WatchRescanner under per-tick limits"
Cohesion: 0.29
Nodes (6): ADR-0062 — R12c: the Watch re-scan scheduler re-researches through the WatchRescanner under per-tick limits, Consequences, Context, Decision, Files changed, Verification

### Community 214 - "ADR-0063 — R12d: the re-scan outcome is visible in the dossier panel and on the Re-scan page"
Cohesion: 0.29
Nodes (6): ADR-0063 — R12d: the re-scan outcome is visible in the dossier panel and on the Re-scan page, Consequences, Context, Decision, Files changed, Verification

### Community 215 - "ADR-0064 — R14: reversible creator archive, respecting the append-only evidence trail"
Cohesion: 0.29
Nodes (6): ADR-0064 — R14: reversible creator archive, respecting the append-only evidence trail, Consequences, Context, Decision, Files changed, Verification

### Community 216 - "test_evidence_provenance_constructors.py"
Cohesion: 0.43
Nodes (6): _evidence_calls(), parametrize, Path, Provenance Invariant (CORP1 Stage 4 acceptance): no Evidence row is ever…, test_every_evidence_constructor_sets_type_and_origin(), test_scan_actually_finds_constructors()

### Community 217 - "DiscoveryScanScheduler"
Cohesion: 0.09
Nodes (22): DiscoveryDeferredError, DiscoveryHandle, DiscoveryScanScheduler, async_sessionmaker, AsyncSession, Exception, A provider plus how to release it once the tick is done., In-process loop running one :func:`run_discovery_pass` per tick. Start it from… (+14 more)

### Community 218 - "Settings"
Cohesion: 0.13
Nodes (24): BaseSettings, Treat DISCOVERY_TOPICS_PER_PASS= (blank) as unset. .env files carry everything…, Settings, AdapterConfigError, build_search_adapter(), Exception, The requested platform is unknown or not configured., Adapter for creator DISCOVERY via keyword search (``ytsearchN:`` syntax).… (+16 more)

### Community 219 - "score_purchase_intent"
Cohesion: 0.33
Nodes (6): From TransactionProvider evidence — marketplace sales, Kickstarter/ Indiegogo…, score_purchase_intent(), test_purchase_intent_at_cap(), test_purchase_intent_monotonic(), test_purchase_intent_positive(), test_purchase_intent_zero_evidence()

### Community 220 - "Slice 1 — Campaign Persistence"
Cohesion: 0.33
Nodes (5): New constraint for future slices, Problems found and fixed during this slice, Slice 1 — Campaign Persistence, Unresolved, pre-existing issues (not touched — out of scope for Slice 1), What shipped

### Community 221 - "Slice 2 — Canonical Niche Persistence"
Cohesion: 0.33
Nodes (5): Assumptions, Problems found during this slice, Slice 2 — Canonical Niche Persistence, Unresolved, pre-existing issues, What shipped

### Community 222 - "Slice 5 — Generalize ResearchRun"
Cohesion: 0.33
Nodes (5): Architecture tension found and how it was resolved, Problems found during this slice, Slice 5 — Generalize ResearchRun, Unresolved, pre-existing issues, What shipped

### Community 223 - "Slice 9 — Niche Canonicalization & Deduplication"
Cohesion: 0.33
Nodes (5): Acceptance criteria → how each is met, Assumptions and open items, Slice 9 — Niche Canonicalization & Deduplication, Verification, What shipped

### Community 224 - "Slice 10 — Niche Verification"
Cohesion: 0.33
Nodes (5): Acceptance criteria → how each is met, Assumptions and open items, Slice 10 — Niche Verification, Verification, What shipped

### Community 225 - "Slice 11 — Creator Ecosystem Size Estimator"
Cohesion: 0.33
Nodes (5): Acceptance criteria → how each is met, Assumptions and open items, Slice 11 — Creator Ecosystem Size Estimator, Verification, What shipped

### Community 226 - "Slice 12 — Niche Qualification Scoring"
Cohesion: 0.33
Nodes (5): Acceptance criteria and how each is met, Assumptions and open items, Slice 12 — Niche Qualification Scoring, Verification, What shipped

### Community 227 - "Slice 13 — Niche Selection"
Cohesion: 0.33
Nodes (5): Acceptance criteria and how each is met, Assumptions and open items, Slice 13 — Niche Selection, Verification, What shipped

### Community 228 - "Slice 14 — Creator Onboarding from Selected Niches"
Cohesion: 0.33
Nodes (5): Acceptance criteria and how each is met, Assumptions and open items, Slice 14 — Creator Onboarding from Selected Niches, Verification, What shipped

### Community 229 - "Slice 15 — Campaign Research Batch"
Cohesion: 0.33
Nodes (5): Acceptance criteria and how each is met, Assumptions and open items, Slice 15 — Campaign Research Batch, Verification, What shipped

### Community 230 - "Slice 16 — Campaign & Niche API Visibility"
Cohesion: 0.33
Nodes (5): Acceptance criteria and how each is met, Assumptions and open items, Slice 16 — Campaign & Niche API Visibility, Verification, What shipped

### Community 231 - "2. Capability decomposition + reuse verdicts"
Cohesion: 0.33
Nodes (6): 2. Capability decomposition + reuse verdicts, Foundation, Intelligence, Presentation, Scoring, evidence, workflow — **this is where CIP reuse dominates (see §4)**, Source acquisition — **two adapter families**

### Community 232 - "Step 0 — Project Scaffold (Adopt CIP)"
Cohesion: 0.33
Nodes (6): 0.1 Python project setup, 0.2 Database scaffold, 0.3 Directory structure, 0.4 Config, 0.5 CI/test harness, Step 0 — Project Scaffold (Adopt CIP)

### Community 233 - ".oxlintrc.json"
Cohesion: 0.33
Nodes (5): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema

### Community 234 - "CampaignStatus"
Cohesion: 0.60
Nodes (4): CampaignStatus, str, CampaignResponse, test_campaign_schema_round_trip()

### Community 235 - "test_discovery_endpoint.py"
Cohesion: 0.08
Nodes (12): captured(), client(), fixture, API tests for POST /discovery/run — both entry points the spec freezes., A status read is for diagnosing trouble, so it must survive it., Swap the registry and the work function so no pipeline actually runs., Installing CORP must not start unattended LLM spend., Copying .env.example and leaving the override empty must not raise an… (+4 more)

### Community 236 - "finish_run returns a status; a fully failed run is kept"
Cohesion: 0.40
Nodes (4): finish_run returns a status; a fully failed run is kept, Not changed, Tests, What changed

### Community 237 - "Step 2 — YouTube Adapter (Wrap google-api-python-client)"
Cohesion: 0.40
Nodes (5): 2.1 Normalized adapter interface (`workers/adapters/base.py`), 2.2 YouTube adapter (`workers/adapters/youtube.py`), 2.3 Acquisition orchestrator (`workers/acquisition/collector.py`), 2.4 Tests, Step 2 — YouTube Adapter (Wrap google-api-python-client)

### Community 238 - "Step 3 — Content + Audience Intelligence (Wrap Gemini)"
Cohesion: 0.40
Nodes (5): 3.1 Provider routing (`workers/providers/registry.py`), 3.2 Topic classification (`workers/intelligence/topics.py`), 3.3 Problem extraction (`workers/intelligence/extraction.py`), 3.4 Tests, Step 3 — Content + Audience Intelligence (Wrap Gemini)

### Community 239 - "Step 6 — Scoring + Confidence (Adapt CIP Steps 9 + 12)"
Cohesion: 0.40
Nodes (5): 6.1 YAML decision rules (`rules/scoring.yaml`), 6.2 Scoring engine (`core/scoring/engine.py`), 6.3 Confidence banding (`core/scoring/confidence.py`), 6.4 Tests, Step 6 — Scoring + Confidence (Adapt CIP Steps 9 + 12)

### Community 240 - "Step 8 — Minimal Console + Gate A (Mirror CIP Step 14)"
Cohesion: 0.40
Nodes (5): 8.1 FastAPI read/write API (`api/`), 8.2 Gate A logic (`core/state/gates.py`), 8.3 React console (`web/`), 8.4 Tests, Step 8 — Minimal Console + Gate A (Mirror CIP Step 14)

### Community 241 - "stub_fair"
Cohesion: 0.09
Nodes (17): _cfg(), fixture, Install a fake ``fair.embedded.module.FAIR`` class for build_fair_provider to…, Fake FAIR that accepts CORP's full kwarg set., An installed FAIR that doesn't accept ``env_file`` should be retried without…, Signature so different that no kwargs match — must raise FairUnavailableError…, A FAIR that reads a bad env file at construction, or otherwise raises, should…, FAIR constructs fine, then ``router.providers()`` blows up (e.g. an older… (+9 more)

### Community 242 - "CreatorNicheResponse"
Cohesion: 0.67
Nodes (3): CreatorNicheCreate, CreatorNicheResponse, BaseModel

### Community 243 - "StackExchangeAdapter"
Cohesion: 0.13
Nodes (8): Any, AsyncClient, datetime, retry, ProblemProvider (CORP1 Stage 4/5, T2): "How do I X?" questions are a direct…, Collects questions (and their answers) from a Stack Exchange site. Each…, StackExchangeAdapter, _ts()

### Community 244 - "Step 1 — Core Data Model (Adapt CIP Evidence Model)"
Cohesion: 0.50
Nodes (4): 1.1 Core entities (SQLAlchemy models + Pydantic schemas), 1.2 Alembic migration, 1.3 Tests, Step 1 — Core Data Model (Adapt CIP Evidence Model)

### Community 245 - "Step 4 — Problem Clustering (Adopt BERTopic / HDBSCAN)"
Cohesion: 0.50
Nodes (4): 4.1 Embeddings (`workers/intelligence/embeddings.py`), 4.2 Clustering (`workers/intelligence/clustering.py`), 4.3 Tests, Step 4 — Problem Clustering (Adopt BERTopic / HDBSCAN)

### Community 246 - "Step 5 — Commercial Intent (Build rules table + Wrap Gemini)"
Cohesion: 0.50
Nodes (4): 5.1 Intent rules table (`core/intent/hierarchy.py` + `rules/intent.yaml`), 5.2 Intent classifier (`workers/intelligence/intent.py`), 5.3 Tests, Step 5 — Commercial Intent (Build rules table + Wrap Gemini)

### Community 247 - "React + TypeScript + Vite"
Cohesion: 0.50
Nodes (3): Expanding the Oxlint configuration, React Compiler, React + TypeScript + Vite

### Community 268 - "test_trend_scan.py"
Cohesion: 0.23
Nodes (23): Turns the broad-topic catalogue into a ranked list of seed topics.…, TrendScanner, _config(), _discovery(), _FakeTrends, Unit tests for the Level 0 trend scan (CORP1 Step 1)., A topic Trends could not score must not jump a topic it did., The crawler must keep crawling when the ranking signal is absent. (+15 more)

### Community 271 - "sync.py"
Cohesion: 0.18
Nodes (20): _get_store(), mirror_content_items(), mirror_interactions(), mirror_metrics(), mirror_observations(), mirror_research_queries(), mirror_scores(), model_to_dict() (+12 more)

### Community 275 - "trend_scan.py"
Cohesion: 0.15
Nodes (13): DiscoveryConfig, AsyncSession, datetime, True when ``keyword`` already matches a canonical Niche (or alias) whose…, See :func:`registry_fresh` -- the drill engine and the Level 0 trend scan must…, registry_fresh(), AsyncSession, CORP1 Step 1, Level 0 — the autonomous trend scan. The drill engine… (+5 more)

### Community 276 - "load_scoring_rules"
Cohesion: 0.12
Nodes (15): load_scoring_rules(), AsyncSession, Path, AsyncSession, test_rules_v2_weights_sum_to_one_and_cover_ten_components(), test_v2_aggregate_uses_all_weights(), The real rules file, not a fixture -- catches a future rebalancing mistake…, The sum-to-one check alone would let a silent reweighting (still summing to… (+7 more)

### Community 277 - "._get_engine"
Cohesion: 0.15
Nodes (7): AsyncEngine, Path, Return {id: raw_text} for the given evidence IDs., Return {id: embedding_bytes} for the given observation IDs., Return {table_name: row_count} for every warm table., Export every table to a JSONL file under out_dir. Returns row counts., Create all warm-store tables (idempotent), then heal column drift.…

### Community 278 - "LLMProvider"
Cohesion: 0.12
Nodes (11): AsyncSession, AsyncSession, Ask the provider to identify niches from ``texts``; keep only the ones whose…, synthesize_niches(), SynthesizedNiche, AsyncSession, LLMProvider, ABC (+3 more)

### Community 279 - "jobs.py"
Cohesion: 0.27
Nodes (14): _close(), _commit_or_rollback(), _embedder_factory(), _singleton(), Any, In-process background jobs for long-running pipelines. The console needs to…, Persist whatever a crashing pipeline flushed (e.g. a failed ResearchRun). If…, Run one stage. ``collect`` needs platform + identifier. (+6 more)

### Community 280 - "_score_from_items"
Cohesion: 0.21
Nodes (10): Any, Pull a 0..100 momentum score out of whatever the adapter returned. With…, _score_from_items(), _Item, Stands in for NormalizedContent — only .metadata is read., No pytrends: the adapter returns keyword-matched trending items with no…, test_score_ignores_unparseable_interest(), test_score_prefers_avg_interest_and_clamps() (+2 more)

### Community 281 - "test_mirror_embeddings.py"
Cohesion: 0.22
Nodes (10): embedding_to_bytes(), Serialize an observation embedding for the warm store's BLOB column. The ORM…, _obs(), MonkeyPatch, ndarray, parametrize, Path, Embeddings must survive the Postgres -> warm store mirror as float32 bytes. The… (+2 more)

### Community 282 - "PooledProvider"
Cohesion: 0.22
Nodes (3): PooledProvider, Any, test_empty_pool_rejected()

### Community 283 - "CompetitorStrength"
Cohesion: 0.29
Nodes (10): CompetitorStrength, str, Higher = more whitespace (less saturated), matching the "higher is better"…, score_competitor_saturation(), test_competitor_saturation_above_cap_clamped(), test_competitor_saturation_empty_list_neutral(), test_competitor_saturation_fully_saturated(), test_competitor_saturation_mixed() (+2 more)

### Community 284 - "patched_pipeline"
Cohesion: 0.25
Nodes (7): _FakeRun, patched_pipeline(), discover(), qualify_campaign(), fixture, Replace the drill engine and qualifier so these tests exercise the pass's own…, discover()

### Community 285 - "score_audience_dissatisfaction"
Cohesion: 0.33
Nodes (6): From DissatisfactionProvider evidence — low-star reviews, complaints about…, score_audience_dissatisfaction(), test_audience_dissatisfaction_at_cap(), test_audience_dissatisfaction_higher_is_stronger_signal(), test_audience_dissatisfaction_positive(), test_audience_dissatisfaction_zero_evidence()

### Community 286 - "score_audience_problem_frequency"
Cohesion: 0.33
Nodes (6): score_audience_problem_frequency(), test_frequency_above_cap(), test_frequency_at_cap(), test_frequency_negative(), test_frequency_positive(), test_frequency_zero()

## Knowledge Gaps
- **625 isolated node(s):** `corp`, `FakeCluster`, `FakeOppScore`, `FakeObservation`, `$schema` (+620 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1972 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **62 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `NormalizedContent` connect `NormalizedContent` to `MultiSourceDiscovery`, `test_captions.py`, `YouTubeAdapter`, `ComplianceStatus`, `build_adapter`, `test_niche_discovery.py`, `AcquisitionCollector`, `Niche`, `._persist_items`, `MarketplaceAdapter`, `ResearchRun`, `AmazonReviewAdapter`, `PatreonSubstackAdapter`, `AppStoreAdapter`, `EvidenceType`, `CrowdfundingAdapter`, `GoogleTrendsAdapter`, `WikipediaAdapter`, `YtDlpAdapter`, `SearchDemandAdapter`, `HackerNewsAdapter`, `test_discovery.py`, `StackExchangeAdapter`, `test_multi_discovery.py`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `ComplianceStatus` connect `ComplianceStatus` to `OpportunityScore`, `test_captions.py`, `test_reddit_adapter.py`, `CompetitivePipeline`, `test_endpoints.py`, `integration/test_cluster_pipeline.py`, `test_models_db.py`, `YouTubeAdapter`, `Evidence`, `build_adapter`, `test_niche_discovery.py`, `AcquisitionCollector`, `Niche`, `_seed_full`, `MarketplaceAdapter`, `test_handoff_endpoint.py`, `test_intelligence_pipeline.py`, `ResearchRun`, `AmazonReviewAdapter`, `PatreonSubstackAdapter`, `AppStoreAdapter`, `EvidenceType`, `test_watch_rescanner.py`, `CrowdfundingAdapter`, `GoogleTrendsAdapter`, `WikipediaAdapter`, `test_registry_rescan.py`, `test_web_adapter.py`, `YtDlpAdapter`, `SearchDemandAdapter`, `HackerNewsAdapter`, `test_corp2_export.py`, `test_niche_candidates.py`, `test_discovery.py`, `test_product_ideation.py`, `EvidenceOrigin`, `NormalizedContent`, `StackExchangeAdapter`, `test_dossier_persistence.py`, `test_multi_discovery.py`, `NicheLifecycleStatus`, `test_niche_canonicalization.py`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `LLMProvider` connect `LLMProvider` to `ResearchOrchestrator`, `test_fair_provider.py`, `CompetitivePipeline`, `IntelligencePipeline`, `ScriptedProvider`, `Evidence`, `SignalLevel`, `extract_observations`, `ComplianceStatus`, `test_provider_registry.py`, `trend_scan.py`, `test_niche_discovery.py`, `LLMCallError`, `test_discovery_scan.py`, `Embedder`, `Niche`, `product_ideation.py`, `PooledProvider`, `build_provider`, `test_intelligence_pipeline.py`, `ResearchRun`, `test_coerce.py`, `ProviderExhaustedError`, `DiscoveryScanScheduler`, `Settings`, `app.py`, `test_niche_candidates.py`, `test_product_ideation.py`, `test_niche_naming.py`, `test_groq_provider.py`, `providers/registry.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 46 inferred relationships involving `NormalizedContent` (e.g. with `AcquisitionCollector` and `_is_interaction()`) actually correct?**
  _`NormalizedContent` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `ResearchRun` (e.g. with `_mark_orphaned_runs()` and `get_evidence()`) actually correct?**
  _`ResearchRun` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 86 inferred relationships involving `ComplianceStatus` (e.g. with `create_evidence()` and `EvidenceCreate`) actually correct?**
  _`ComplianceStatus` has 86 INFERRED edges - model-reasoned connections that need verification._
- **Are the 86 inferred relationships involving `AccessMethod` (e.g. with `create_evidence()` and `EvidenceCreate`) actually correct?**
  _`AccessMethod` has 86 INFERRED edges - model-reasoned connections that need verification._