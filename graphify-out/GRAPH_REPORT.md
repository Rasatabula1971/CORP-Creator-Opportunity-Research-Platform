# Graph Report - CORP-Creator-Opportunity-Research-Platform  (2026-09-23)

## Corpus Check
- 389 files · ~238,730 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: (none) 5, .example 2, .ini 1)

## Summary
- 5272 nodes · 15290 edges · 282 communities (221 shown, 61 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 2329 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8c57360a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SignalLevel
- CreatorStatus
- test_scoring_engine.py
- CORP Implementation Steps — Coding Roadmap
- test_fair_provider.py
- ConfidenceBand
- cluster_pipeline.py
- test_endpoints.py
- Niche
- IntelligencePipeline
- YouTubeAdapter
- test_intent_pipeline.py
- test_intent_classifier.py
- What You Must Do When Invoked
- extract_observations
- models/evidence.py
- test_dossier_generator.py
- providers/registry.py
- CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1
- test_youtube_trends_adapter.py
- test_niche_discovery.py
- classify_topics
- NormalizedContent
- Embedder
- ProblemCluster
- YouTubeTrendsAdapter
- MarketplaceAdapter
- load_yaml_rules
- graphify reference: extra exports and benchmark
- CORP Search-Before-Build Checklist
- test_migration.py
- graphify reference: query, path, explain
- Creator
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
- intelligence/errors.py
- AppStoreAdapter
- StackExchangeAdapter
- test_capabilities.py
- ProviderExhaustedError
- test_watch_rescanner.py
- CrowdfundingAdapter
- GoogleTrendsAdapter
- WikipediaAdapter
- _TextAndLinks
- test_registry_rescan.py
- CampaignNiche
- test_web_adapter.py
- routes_ops.py
- build_adapter
- .select
- SearchDemandAdapter
- test_source_health.py
- HackerNewsAdapter
- test_corp2_export.py
- register_error_handlers
- ._score_opportunity
- test_runs.py
- lifespan
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
- test_stage4_models.py
- RedditAdapter
- scoring/niche_qualification.py
- test_dossier_persistence.py
- require_api_key
- test_onboarding_enrichment.py
- test_niche_naming.py
- test_groq_provider.py
- test_multi_discovery.py
- NicheLifecycleStatus
- workers/test_scoring_pipeline.py
- package.json
- test_niche_canonicalization.py
- LLMCallError
- CampaignNicheStatus
- MultiSourceDiscovery
- ComplianceStatus
- ResearchOrchestrator
- RegistryRescanScheduler
- test_campaign_endpoints.py
- advance
- CompetitivePipeline
- CampaignDetailPage.tsx
- niche_discovery.py
- 3. Product specification (Stage 3 — to freeze)
- ScriptedProvider
- RunType
- engine.py
- compilerOptions
- NicheQualifier
- PruneService
- embed_texts
- WebPresenceAdapter
- ._put
- compilerOptions
- test_discovery_scan.py
- ClusterPipeline
- schemas/niche.py
- propose_ideas
- Decisions
- ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator
- SourceHealthTracker
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
- _make_session_factory
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
- test_error_handlers.py
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
- app.py
- Settings
- test_coerce.py
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
- SourceHealthRecord
- test_discovery_endpoint.py
- finish_run returns a status; a fully failed run is kept
- Step 2 — YouTube Adapter (Wrap google-api-python-client)
- Step 3 — Content + Audience Intelligence (Wrap Gemini)
- Step 6 — Scoring + Confidence (Adapt CIP Steps 9 + 12)
- Step 8 — Minimal Console + Gate A (Mirror CIP Step 14)
- stub_fair
- score_solution_saturation
- is_public_url
- Step 1 — Core Data Model (Adapt CIP Evidence Model)
- Step 4 — Problem Clustering (Adopt BERTopic / HDBSCAN)
- Step 5 — Commercial Intent (Build rules table + Wrap Gemini)
- React + TypeScript + Vite
- FakeYouTubeSearchAdapter
- test_trend_scan.py
- tsconfig.json
- pytest_sessionfinish
- collector.py
- mock_session
- ._get_engine
- LLMProvider
- jobs.py
- CompetitorStrength
- patched_pipeline
- score_audience_dissatisfaction

## God Nodes (most connected - your core abstractions)
1. `NormalizedContent` - 215 edges
2. `ResearchRun` - 178 edges
3. `ComplianceStatus` - 163 edges
4. `AccessMethod` - 162 edges
5. `Niche` - 155 edges
6. `Creator` - 132 edges
7. `Evidence` - 128 edges
8. `Campaign` - 104 edges
9. `CreatorStatus` - 104 edges
10. `EvidenceType` - 96 edges

## Surprising Connections (you probably didn't know these)
- `test_youtube_is_the_default_momentum_source()` --uses--> `Settings`  [INFERRED]
  tests/workers/test_discovery_scan.py → corp/config.py
- `test_every_evidence_type_has_exactly_one_interface()` --uses--> `EvidenceType`  [INFERRED]
  tests/workers/test_capabilities.py → corp/core/models/evidence.py
- `captured()` --uses--> `JobRegistry`  [INFERRED]
  tests/api/test_discovery_endpoint.py → corp/api/jobs.py
- `test_run_pipeline_unknown_kind_raises()` --calls--> `run_pipeline()`  [EXTRACTED]
  tests/api/test_ops_no_db.py → corp/api/jobs.py
- `fake_fair()` --uses--> `Settings`  [INFERRED]
  tests/workers/test_provider_factory.py → corp/config.py

## Import Cycles
- None detected.

## Communities (282 total, 61 thin omitted)

### Community 0 - "SignalLevel"
Cohesion: 0.17
Nodes (22): classify_signal_level(), load_intent_rules(), _matches_keyword(), Any, Path, Whole-word/phrase match, case-insensitive. A bare substring test made "vs" fire…, Rules-table classification. Match indicators against the hierarchy., str (+14 more)

### Community 1 - "CreatorStatus"
Cohesion: 0.20
Nodes (23): CreatorStatus, str, InvalidTransitionError, Exception, validate_transition(), Session-aware creator status transitions used by the pipelines. Pipelines call…, Unit tests for Gate A state transitions., test_decision_type_maps_to_status() (+15 more)

### Community 2 - "test_scoring_engine.py"
Cohesion: 0.07
Nodes (46): get_score_band(), Any, From TrendProvider + SearchIntentProvider evidence (Google Trends interest,…, From TransactionProvider evidence — marketplace sales, Kickstarter/ Indiegogo…, score_audience_problem_frequency(), score_commercial_intent(), score_creator_reach(), score_evidence_depth() (+38 more)

### Community 3 - "CORP Implementation Steps — Coding Roadmap"
Cohesion: 0.22
Nodes (9): 7.1 Dossier template (`workers/dossier/templates/dossier.html.j2`), 7.2 Dossier engine (`workers/dossier/generator.py`), 7.3 Tests, CORP Implementation Steps — Coding Roadmap, Deferred (Only If Thin Slice Earns It), Implementation Order & Dependencies, Key Architectural Decisions (Pre-resolved), Phasing Strategy (+1 more)

### Community 4 - "test_fair_provider.py"
Cohesion: 0.09
Nodes (45): ProviderError, Exception, FairProvider, _model_label(), Any, LLMProvider backed by an in-process FAIR router. ``router`` is a…, The model that answered the last call (vendor-canonical label, e.g.…, Every model FAIR may route to, plus the pre-call label: one family for… (+37 more)

### Community 5 - "ConfidenceBand"
Cohesion: 0.27
Nodes (15): ConfidenceBand, str, compute_confidence_band(), Any, Confidence banding driven by YAML thresholds when provided. Args: thresholds:…, Regression: 90-365 days used to silently fall through to MEDIUM instead of…, test_custom_thresholds_override_defaults(), test_degrades_to_low_past_medium_max_days() (+7 more)

### Community 6 - "cluster_pipeline.py"
Cohesion: 0.11
Nodes (36): Clustering pipeline — embed observations, cluster, persist to DB, unify topics., _build_clusters(), cluster_observations(), ClusteringConfig, ClusterResult, _generate_label(), _pick_representative(), datetime (+28 more)

### Community 7 - "test_endpoints.py"
Cohesion: 0.23
Nodes (30): _make_client(), AsyncClient, asyncio, AsyncSession, MonkeyPatch, parametrize, API endpoint tests against real Postgres., research_more is a dossier-gate decision; Gate A must say so, not 500. (+22 more)

### Community 8 - "Niche"
Cohesion: 0.06
Nodes (97): Campaign, CampaignStatus, str, The top-level research execution unit above niche and creator research. A…, Niche, NichePolicyClass, Configuration-driven policy tier (ADR-008); classification rules live outside…, Canonical niche identity. A broad domain (e.g. "Fitness") is a discovery input,… (+89 more)

### Community 9 - "IntelligencePipeline"
Cohesion: 0.12
Nodes (13): IntelligencePipeline, Any, Extract per-comment + cross-comment observations, one content item at a time.…, Run one batched extraction and persist its observations., Mark an interaction as extracted under the current prompt + model., True when this interaction was already extracted by the current prompt version…, Save single-comment observations against a specific evidence row., Newest evidence row for a source id (re-collection appends, never updates). (+5 more)

### Community 10 - "YouTubeAdapter"
Cohesion: 0.06
Nodes (31): describe_http_error(), _extract_channel_id(), _http_error_reason(), _parse_iso8601_duration(), Any, BaseException, datetime, HttpError (+23 more)

### Community 11 - "test_intent_pipeline.py"
Cohesion: 0.25
Nodes (12): FakeProvider, asyncio, AsyncSession, Integration tests for IntentPipeline against real Postgres., Create creator → evidence → observations → cluster with members., _seed_cluster(), test_intent_pipeline_creates_commercial_signal(), test_intent_pipeline_creates_evidence() (+4 more)

### Community 12 - "test_intent_classifier.py"
Cohesion: 0.11
Nodes (25): _as_list(), classify_cluster_intent(), IntentClassification, _llm_classify(), Any, Commercial intent classification via LLM + rules hierarchy., Model output is untrusted: only a real list is iterated as indicators., Take the higher of rules-table and LLM classifications. (+17 more)

### Community 13 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 14 - "extract_observations"
Cohesion: 0.16
Nodes (15): extract_observations(), Extract problem observations from a single comment. Raises ``LLMCallError``…, FailingProvider, FakeProvider, Unit tests for problem extraction — LLM calls mocked., A dead provider must not look like an empty comment., Returns canned JSON responses., test_extract_observations_basic() (+7 more)

### Community 15 - "models/evidence.py"
Cohesion: 0.05
Nodes (69): infer_evidence_type(), Lenient platform → evidence-type lookup; write paths use the strict…, _is_retryable(), BaseException, Amazon review adapter — 1-3 star reviews as unmet-need signals. Low-star Amazon…, _is_retryable(), _parse_iso(), BaseException (+61 more)

### Community 16 - "test_dossier_generator.py"
Cohesion: 0.23
Nodes (27): FakeAccount, FakeCluster, FakeCompetitor, FakeCreator, FakeCreatorScore, FakeDataCoverage, FakeObservation, FakeOpportunity (+19 more)

### Community 17 - "providers/registry.py"
Cohesion: 0.07
Nodes (36): classify_quota_error(), _finish_reason(), GeminiProvider, ABC, Any, BaseException, LLM provider abstraction with deterministic call logging., Why the first candidate stopped, for error messages; None when unknown. (+28 more)

### Community 18 - "CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1"
Cohesion: 0.14
Nodes (14): 0. What "using CIP" means here, 1. Two findings before you build, 3. Prior art — five candidate repos (search-before-build gate, executed), 4. The headline: CORP and CIP share DNA, 5. Repo skeleton (respects your import-linter discipline), 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only), 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero), 8. Open decisions for you (+6 more)

### Community 19 - "test_youtube_trends_adapter.py"
Cohesion: 0.05
Nodes (75): Exception, QuotaExceededError, Raised when YouTube API daily quota would be exceeded., RuntimeError, The words a video must contain to count toward ``topic``., The chart could not be loaded; momentum is unavailable for now. Every load…, topic_terms(), TrendChartUnavailableError (+67 more)

### Community 20 - "test_niche_discovery.py"
Cohesion: 0.17
Nodes (50): NicheCandidate, NicheCandidateStatus, str, Broad topic -> capability fan-out -> LLM synthesis -> recurse. ``provider`` is…, RecursiveNicheDiscovery, _config(), _content(), _FakeTrendAdapter (+42 more)

### Community 21 - "classify_topics"
Cohesion: 0.18
Nodes (12): classify_topics(), Any, Classify a creator's content into topics. Args: provider: LLM provider…, FailingProvider, FakeProvider, Unit tests for topic classification — LLM calls mocked., test_classify_topics_basic(), test_classify_topics_clamps_confidence() (+4 more)

### Community 22 - "NormalizedContent"
Cohesion: 0.06
Nodes (36): AcquisitionCollector, _content_extra(), _int_or_none(), _is_interaction(), Any, AsyncSession, Update the platform account's follower count and append a snapshot., Find the ContentItem a comment/reply/question/review belongs to. (+28 more)

### Community 23 - "Embedder"
Cohesion: 0.15
Nodes (11): AsyncSession, embed_texts_async(), Embedder, ndarray, Protocol, Embedding generation for ProblemObservation text using sentence-transformers., Protocol for anything that can embed text into vectors., ``embed_texts`` on a worker thread. Pipelines run on the API process's event… (+3 more)

### Community 24 - "ProblemCluster"
Cohesion: 0.07
Nodes (77): Base, generate_uuid(), TimestampMixin, Competitor, CompetitorType, An existing product/creator/workaround already serving a problem cluster's…, AudienceInteraction, ContentItem (+69 more)

### Community 25 - "YouTubeTrendsAdapter"
Cohesion: 0.12
Nodes (10): ChartVideo, _fold(), Any, retry, Light plural folding: "games" → "game", "aquariums" → "aquarium". Deliberately…, ``TrendProvider`` backed by YouTube's official trending charts., ``chart`` returns the raw trending corpus (for inspection); anything else is…, _to_chart_video() (+2 more)

### Community 27 - "MarketplaceAdapter"
Cohesion: 0.06
Nodes (43): _extract_price(), _html_to_text(), MarketplaceAdapter, _parse_etsy_api_response(), _parse_etsy_listings(), _parse_gumroad_listings(), _parse_udemy_response(), Any (+35 more)

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

### Community 34 - "Creator"
Cohesion: 0.07
Nodes (72): archive_creator(), _as_utc(), create_decision(), generate_persisted_dossier(), _generate_product_ideas_best_effort(), get_campaign(), get_competitors(), get_creator() (+64 more)

### Community 35 - "build_provider"
Cohesion: 0.10
Nodes (43): build_provider(), ProviderConfigError, Exception, No usable LLM provider is configured., Return the LLMProvider selected by configuration., FairUnavailableError, Exception, FAIR cannot be used in this process (not installed, or no provider key). (+35 more)

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
Cohesion: 0.06
Nodes (58): _mark_orphaned_runs(), Mark ResearchRun rows stuck in 'running' as 'failed' on startup., Any, str, Stored as plain strings on ResearchRun.status., ResearchRun, RunScope, RunStatus (+50 more)

### Community 73 - "run.py"
Cohesion: 0.15
Nodes (24): _singleton(), Any, Production embedder using sentence-transformers (local, free)., SentenceTransformerEmbedder, CandidateConfig, _close(), main(), Run a pipeline from the command line using the configured provider/adapter.… (+16 more)

### Community 75 - "WarmStore"
Cohesion: 0.13
Nodes (13): SQLite table definitions for the CORP warm store. Mirrors the PostgreSQL…, Path, WarmStore — async SQLite store for bulk CORP data. Provides idempotent put/get…, Export every table to a JSONL file under out_dir. Returns row counts., Async SQLite store for bulk CORP data (evidence, embeddings, content)., WarmStore, Functional check that mirroring a real ProblemObservation row doesn't crash.…, test_mirror_observations_accepts_sentiment_and_urgency() (+5 more)

### Community 76 - "AmazonReviewAdapter"
Cohesion: 0.05
Nodes (46): AmazonReviewAdapter, _extract_asins(), _html_to_text(), _parse_review_date(), _parse_reviews(), AsyncClient, datetime, HTMLParser (+38 more)

### Community 77 - "CreatorOnboarder"
Cohesion: 0.22
Nodes (22): CreatorOnboarder, Any, Search a niche and return every unique channel (no band filter, no cap).…, One deduplicated, batched subscriber-count lookup for the whole run., _FakeItem, FakeSearchAdapter, asyncio, AsyncSession (+14 more)

### Community 78 - "PatreonSubstackAdapter"
Cohesion: 0.06
Nodes (40): _extract_tiers(), _parse_substack_date(), _parse_substack_response(), PatreonSubstackAdapter, Any, AsyncClient, datetime, retry (+32 more)

### Community 79 - "intelligence/errors.py"
Cohesion: 0.16
Nodes (18): as_bool(), as_float(), as_int(), Any, Defensive coercion of untrusted LLM JSON values. Model output is not shape-…, Coerce ``value`` to float, returning ``default`` if it isn't numeric., Coerce ``value`` to int, returning ``default`` if it isn't a whole number.…, Coerce ``value`` to bool, treating the string "false"/"0"/"no"/… as False.… (+10 more)

### Community 80 - "AppStoreAdapter"
Cohesion: 0.07
Nodes (32): AppStoreAdapter, _parse_review_feed(), Any, AsyncClient, retry, Collects app reviews from Apple's App Store via RSS feed. Each review becomes a…, Evidence of what solutions already exist — the competitive landscape., SolutionProvider (+24 more)

### Community 81 - "StackExchangeAdapter"
Cohesion: 0.09
Nodes (33): Any, AsyncClient, datetime, retry, ProblemProvider (CORP1 Stage 4/5, T2): "How do I X?" questions are a direct…, Collects questions (and their answers) from a Stack Exchange site. Each…, StackExchangeAdapter, _ts() (+25 more)

### Community 82 - "test_capabilities.py"
Cohesion: 0.07
Nodes (37): DissatisfactionProvider, EvidenceProvider, MonetisationProvider, PlanningIntentProvider, ProblemProvider, ABC, Evidence that creators or products in this space already earn money., Evidence that current solutions are not good enough. (+29 more)

### Community 83 - "ProviderExhaustedError"
Cohesion: 0.12
Nodes (32): ProviderExhaustedError, ProviderUnavailableError, Provider health signals the pool acts on. Only these two trigger failover.…, A quota that will not clear inside one call's retry window. ``retry_after`` is…, Transient failure (5xx, timeout, transport) that outlasted the retry budget., Failover across free-tier providers. Same ``LLMProvider`` interface, so…, Clock, daily() (+24 more)

### Community 84 - "test_watch_rescanner.py"
Cohesion: 0.16
Nodes (38): RuntimeError, A stage of the re-research chain failed; the message names it., RescanError, _d(), FakeDriller, FakeIdeator, FakeResearcher, PoisoningIdeator (+30 more)

### Community 85 - "CrowdfundingAdapter"
Cohesion: 0.08
Nodes (31): CrowdfundingAdapter, _parse_indiegogo_date(), _parse_indiegogo_response(), _parse_kickstarter_response(), Any, AsyncClient, datetime, retry (+23 more)

### Community 86 - "GoogleTrendsAdapter"
Cohesion: 0.08
Nodes (29): GoogleTrendsAdapter, _has_pytrends(), _parse_rss_date(), _parse_trends_rss(), AsyncClient, datetime, retry, TrendProvider (CORP1 Stage 4/5, T2): delegates to collect() unchanged. (+21 more)

### Community 87 - "WikipediaAdapter"
Cohesion: 0.08
Nodes (27): Any, AsyncClient, retry, TrendProvider (CORP1 Stage 4/5, T2): sustained article pageviews are a demand-…, Collects Wikipedia article summaries with pageview trend data. Each article…, WikipediaAdapter, mock_client(), _mock_resp() (+19 more)

### Community 88 - "_TextAndLinks"
Cohesion: 0.14
Nodes (9): AsyncNetworkStream, parse_page(), Any, HTMLParser, Extract title, description, visible text, and classified outbound links., Network backend that validates DNS at connection time. The pre-flight…, _SSRFSafeBackend, _TextAndLinks (+1 more)

### Community 89 - "test_registry_rescan.py"
Cohesion: 0.07
Nodes (84): Dossier, DossierStatus, str, Denormalized mirror of the latest HumanDecision for fast dashboard queries.…, One decision-ready dossier for one creator x niche x opportunity., creator_status_for_dossiers(), mirror_creator_status(), The creator status implied by its ACTIVE dossiers, by precedence: any approved… (+76 more)

### Community 90 - "CampaignNiche"
Cohesion: 0.12
Nodes (43): CampaignNiche, How one niche performed within one campaign (§12). Never overwrites Niche's own…, _make_client(), AsyncClient, asyncio, AsyncSession, LogCaptureFixture, parametrize (+35 more)

### Community 91 - "test_web_adapter.py"
Cohesion: 0.19
Nodes (16): _adapter(), _html(), public_dns(), resolve(), fixture, Unit tests for the creator-web adapter — HTTP mocked, no network., Every hostname resolves to a public address unless a test overrides it., test_body_is_capped_not_buffered_whole() (+8 more)

### Community 92 - "routes_ops.py"
Cohesion: 0.09
Nodes (48): BackgroundTasks, add_account(), CampaignPipelineRequest, ClusterDetail, create_campaign(), create_creator(), CreatorCreateRequest, discovery_status() (+40 more)

### Community 93 - "build_adapter"
Cohesion: 0.05
Nodes (48): AdapterConfigError, build_adapter(), build_search_adapter(), Exception, Adapter selection — builds a SourceAdapter for a platform name from settings., The requested platform is unknown or not configured., Adapter for creator DISCOVERY via keyword search (``ytsearchN:`` syntax).…, _default_factory() (+40 more)

### Community 94 - ".select"
Cohesion: 0.06
Nodes (26): ColumnElement, growth_ratio(), Relative growth between two snapshot values; None when not measurable., _comparable_products(), DataCoverage, DossierData, DossierGenerator, OpportunityContext (+18 more)

### Community 95 - "SearchDemandAdapter"
Cohesion: 0.09
Nodes (26): Any, AsyncClient, retry, SearchIntentProvider (CORP1 Stage 4/5, T2): autocomplete suggestions reveal…, Collects Google autocomplete suggestions as search-demand signals. Each…, SearchDemandAdapter, _autocomplete_response(), mock_client() (+18 more)

### Community 96 - "test_source_health.py"
Cohesion: 0.16
Nodes (14): Source health tracker — circuit breaker for tolerated adapters. Tracks per-…, SourceStatus, fixture, Tests for the source health tracker — circuit breaker logic., test_degrades_after_threshold(), test_disconnects_after_threshold(), test_failed_probe_rearms_cooldown(), test_load_corrupt_file() (+6 more)

### Community 97 - "HackerNewsAdapter"
Cohesion: 0.09
Nodes (25): HackerNewsAdapter, _parse_ts(), Any, AsyncClient, datetime, retry, Collects stories and comments from Hacker News via Algolia API. Stories become…, ProblemProvider (CORP1 Stage 4/5, T2): delegates to collect() unchanged —… (+17 more)

### Community 98 - "test_corp2_export.py"
Cohesion: 0.16
Nodes (33): build_handoff_package(), EvidenceTrailEntry, HandoffPackage, _isoformat_nested(), NichePathEntry, Any, AsyncSession, Build the frozen Stage 3 handoff package for one dossier. Raises ``ValueError``… (+25 more)

### Community 99 - "register_error_handlers"
Cohesion: 0.14
Nodes (21): _body(), Any, FastAPI, One error shape for the UI to branch on. Every error body carries ``detail``…, register_error_handlers(), _adapter(), _http(), _integrity() (+13 more)

### Community 100 - "._score_opportunity"
Cohesion: 0.08
Nodes (35): load_scoring_rules(), Evidence depth input: observation counts weighted by how they were obtained., 0.5 = flat or unknown; strong growth → 1.0; decline → toward 0., Higher = less saturated = more room for a new product. ``commerce_overlap`` is…, How much the creator already talks about this problem in their own content., Fraction of the creator's audience platforms where the problem shows up.…, score_competition_saturation(), score_creator_content_alignment() (+27 more)

### Community 101 - "test_runs.py"
Cohesion: 0.17
Nodes (13): Advance the creator to ``working`` for the block, then ``done`` on success. The…, stage(), FakeSession, FakeSessionWithCreator, parametrize, Unit tests for the shared run lifecycle helpers — no database., test_resolve_status(), test_stage_completed_run_advances() (+5 more)

### Community 102 - "lifespan"
Cohesion: 0.17
Nodes (16): lifespan(), R12c: the Watch re-scan scheduler's LLM provider, built once and kept for the…, RescanProviders, Exception, Raised by a rescanner factory to defer the whole tick without touching any…, RescanDeferredError, _FakePool, asyncio (+8 more)

### Community 103 - "test_ops_no_db.py"
Cohesion: 0.07
Nodes (19): JobRegistry, JobResponse, JobStatus, BaseModel, str, The in-flight job of a given kind, if any. Campaign-less jobs (an autonomous…, Run ``work`` and record its outcome on ``job``. Never raises., Mark any still-running jobs as failed (called at shutdown). (+11 more)

### Community 104 - "test_niche_candidates.py"
Cohesion: 0.15
Nodes (26): NicheCandidateEvidence, One evidence row's membership in one candidate, with its similarity to the…, NicheCandidateGenerator, Any, Every non-empty evidence row collected by this campaign's discovery runs., Group the campaign's discovery evidence into staged candidates. Returns the run., _candidates(), FakeEmbedder (+18 more)

### Community 105 - "test_discovery.py"
Cohesion: 0.16
Nodes (26): NicheDiscoveryCollector, AsyncSession, skipif, _campaign(), FakeAdapter, asyncio, AsyncSession, Path (+18 more)

### Community 106 - "CampaignResearchBatch"
Cohesion: 0.10
Nodes (42): BatchConfig, CampaignResearchBatch, CreatorResearcher, AsyncSession, Protocol, ResearchReport, T, _FakeReport (+34 more)

### Community 107 - "App.tsx"
Cohesion: 0.14
Nodes (23): react-router-dom, useCampaigns(), useCreateCampaign(), useJobs(), useResearchRuns(), useWatchingDossiers(), LastRescan, Layout() (+15 more)

### Community 108 - "CreatorDetailPage.tsx"
Cohesion: 0.09
Nodes (24): useArchiveCreator(), useClusterObservations(), useClusters(), useCreator(), useDecisions(), useDossier(), useGeneratePersistedDossier(), usePersistedDossier() (+16 more)

### Community 109 - "EcosystemEstimator"
Cohesion: 0.20
Nodes (25): EcoConfig, EcosystemEstimator, AsyncSession, _run_estimate_ecosystem(), FakeEnricher, _FakeItem, FakeSearchAdapter, asyncio (+17 more)

### Community 110 - "test_provider_health.py"
Cohesion: 0.07
Nodes (23): PingResult, Real end-to-end liveness probe: enumerate providers, then run a trivial schema-…, Outcome of a FAIR end-to-end liveness probe. ``ok`` is only true when at least…, client(), _FakeFair, fixture, Tests for /providers/health — the endpoint that reports the active LLM provider…, A bare Gemini/Groq or a PooledProvider isn't a FairProvider — no ping is run,… (+15 more)

### Community 111 - "test_product_ideation.py"
Cohesion: 0.25
Nodes (22): ProductIdea, One LLM-generated, evidence-grounded product idea for one creator's problem…, IdeationConfig, ProductIdeationGenerator, AsyncSession, _config(), _idea(), _make_cluster_with_evidence() (+14 more)

### Community 112 - "hooks.ts"
Cohesion: 0.10
Nodes (29): api, Campaign, CampaignCreateInput, CampaignNiche, CampaignNicheStatus, CampaignStatus, CommercialSignal, CompetitorStrength (+21 more)

### Community 113 - "test_stage4_models.py"
Cohesion: 0.13
Nodes (35): DecisionType, Gate, HumanDecision, Append-only. Every decision is a new row — never update or delete., AsyncSession, Gate A logic — human review decisions with state machine transitions — and the…, Record a Gate A decision and transition the creator's status. Raises…, record_gate_a_decision() (+27 more)

### Community 114 - "RedditAdapter"
Cohesion: 0.08
Nodes (33): Any, AsyncClient, datetime, retry, Newest posts for ``r/<sub>``, ``u/<user>`` or a bare subreddit name., Full comment tree for one post. Collapsed 'more' stubs are skipped., Collects posts and full comment trees from a subreddit or user profile., RedditAdapter (+25 more)

### Community 115 - "scoring/niche_qualification.py"
Cohesion: 0.16
Nodes (25): compute_components(), compute_confidence(), compute_qualification_score(), compute_research_completeness(), load_rules(), _log_score(), NicheInput, Any (+17 more)

### Community 116 - "test_dossier_persistence.py"
Cohesion: 0.25
Nodes (31): ProductIdeaComplexity, ProductIdeaType, str, Matches the CORP1 spec's product-idea vocabulary (Stage 1, step 6)., _make_creator(), _make_evidence(), _make_niche(), _make_run() (+23 more)

### Community 117 - "require_api_key"
Cohesion: 0.24
Nodes (10): Single shared API key. Enough for a one-team console; swap for real auth later., No-op when API_KEY is unset (local dev); otherwise the header must match., require_api_key(), No-DB tests for the shared API-key dependency., Starlette decodes headers as latin-1; non-ASCII chars must not cause a…, test_matching_key_passes(), test_missing_key_rejected(), test_no_key_configured_is_noop() (+2 more)

### Community 118 - "test_onboarding_enrichment.py"
Cohesion: 0.22
Nodes (15): _is_enrichable_channel_id(), OnboardConfig, Only real YouTube channel IDs (``UC`` + 22 chars) can be looked up via the Data…, _Niche, _onboarder(), No-DB unit tests for the onboarding subscriber-count enrichment path. These…, test_enrich_all_dedups_across_niches(), test_enrich_all_failure_is_graceful() (+7 more)

### Community 119 - "test_niche_naming.py"
Cohesion: 0.14
Nodes (25): check_grounding(), ClusterName, name_cluster(), _normalize(), Name an evidence cluster as a niche candidate (Slice 8, §16). The LLM's role…, Ask the provider to name a cluster; verify every cited term against the texts.…, Return the cited terms that do NOT occur in the texts (case/space-insensitive).…, _answer() (+17 more)

### Community 120 - "test_groq_provider.py"
Cohesion: 0.19
Nodes (26): _capture(), handler(), _completion(), _provider(), Unit tests for the Groq provider — HTTP mocked, no network., A long retry-after is passed through for the pool to judge; it is not a daily…, The contract is a JSON object; a top-level list must not leak through., Non-reasoning models reject the parameter, so None/"" must not send it. (+18 more)

### Community 121 - "test_multi_discovery.py"
Cohesion: 0.13
Nodes (15): FakeAdapter, _make_item(), Exception, patch, Tests for multi-source niche discovery — all DB + HTTP calls mocked., test_archive_written(), test_deduplicates_evidence(), test_discover_fans_out() (+7 more)

### Community 122 - "NicheLifecycleStatus"
Cohesion: 0.27
Nodes (19): NicheLifecycleStatus, str, The cycle from §7: CANDIDATE precedes verification; ACTIVE/EXPAND then cycle…, NicheVerifier, AsyncSession, VerifyConfig, _run_verify(), asyncio (+11 more)

### Community 123 - "workers/test_scoring_pipeline.py"
Cohesion: 0.15
Nodes (17): ClusterContext, CreatorContext, Everything about a creator the per-cluster scoring needs, loaded once., _creator_context(), FakeSession, _make_pipe_and_helpers(), _cluster_ctx(), Unit tests for ScoringPipeline configuration plumbing — no database. (+9 more)

### Community 124 - "package.json"
Cohesion: 0.08
Nodes (24): oxlint, react-dom, tailwindcss, @tailwindcss/vite, @types/node, @types/react, @types/react-dom, typescript (+16 more)

### Community 125 - "test_niche_canonicalization.py"
Cohesion: 0.12
Nodes (42): NicheAlias, Alternate wording that resolves to one canonical Niche. Existence of this table…, CanonConfig, NicheCanonicalizer, AsyncSession, The Niche the parent candidate resolved to (PROMOTED or MERGED -- lineage…, True if attaching ``niche_id`` under ``prospective_parent`` would create a…, FakeEmbedder (+34 more)

### Community 126 - "LLMCallError"
Cohesion: 0.19
Nodes (11): extract_creator_problems(), LLMCallError, BaseException, RuntimeError, A single LLM call failed (transport, provider, or unparseable output)., FakeProvider, Unit tests for creator-side extraction — LLM mocked., test_body_is_truncated() (+3 more)

### Community 127 - "CampaignNicheStatus"
Cohesion: 0.30
Nodes (21): CampaignNicheStatus, str, How far this niche has gotten within this specific campaign. Distinct from…, NicheSelector, AsyncSession, SelectionConfig, _run_select(), _make_niche() (+13 more)

### Community 128 - "MultiSourceDiscovery"
Cohesion: 0.20
Nodes (7): MultiSourceDiscovery, Any, AsyncSession, Orchestrates niche discovery across multiple adapters. Usage:: disco =…, Path, test_all_sources_skipped_is_a_failed_run(), test_discover_unknown_campaign()

### Community 129 - "ComplianceStatus"
Cohesion: 0.07
Nodes (64): create_evidence(), AsyncSession, AccessMethod, ComplianceStatus, Evidence, EvidenceOrigin, EvidenceType, str (+56 more)

### Community 130 - "ResearchOrchestrator"
Cohesion: 0.17
Nodes (13): Keep the failed run row a crashing stage flushed. If the session is poisoned…, ResearchOrchestrator, ResearchReport, _fake_session(), _FakeCreator, _orchestrator(), patch, No-DB unit tests for the orchestrator's stage-crash handling. When a stage… (+5 more)

### Community 131 - "RegistryRescanScheduler"
Cohesion: 0.18
Nodes (7): BusyCheck, async_sessionmaker, Protocol, True when a job is already queued/running for this dossier's campaign (``None``…, The in-process scheduled job itself: an asyncio loop ticking every…, RegistryRescanScheduler, RescannerFactory

### Community 132 - "test_campaign_endpoints.py"
Cohesion: 0.29
Nodes (22): _make_client(), AsyncClient, asyncio, AsyncSession, API endpoint tests for campaign read (Slice 16) and write (Slice 17)., CORP1 Stage 5, T4: discover no longer needs a platform -- the recursive…, _seed_campaign_with_niches(), test_campaign_pipeline_conflict() (+14 more)

### Community 133 - "advance"
Cohesion: 0.28
Nodes (14): advance(), AsyncSession, Move ``creator`` to ``target`` if the state machine allows it. Returns True…, Put a creator back to ``previous`` after a failed stage, bypassing validation., restore(), _creator(), FakeSession, Unit tests for session-aware creator transitions — no database. (+6 more)

### Community 134 - "CompetitivePipeline"
Cohesion: 0.11
Nodes (15): CompetitivePipeline, _http_url_or_none(), Keep only http(s) URLs: the dossier renders ``Competitor.url`` into an href., Discovers competitors for each ProblemCluster via LLM analysis., Run competitive discovery for all clusters belonging to a creator., _cluster(), FakeProvider, FakeSession (+7 more)

### Community 135 - "CampaignDetailPage.tsx"
Cohesion: 0.12
Nodes (15): react, @tanstack/react-query, useCampaign(), useCampaignCreators(), useCampaignNiches(), useJob(), useStartCampaignPipeline(), App() (+7 more)

### Community 136 - "niche_discovery.py"
Cohesion: 0.09
Nodes (25): _evidence_supporting(), _fetch_method(), _gather_safely(), matched_exclusion(), _normalize(), Any, AsyncSession, datetime (+17 more)

### Community 137 - "3. Product specification (Stage 3 — to freeze)"
Cohesion: 0.10
Nodes (20): 1. Problem (Stage 1/2 recap), 2. What exists to build on (Stage 2 research, verified in code), 3.1 Watch re-scan (R12), 3.2 Research More completion (R12a — same machinery, do first), 3.3 "The evidence strengthened" — definition (decision needed), 3.4 Cost and safety limits (decision needed), 3.5 Human-visible behaviour, 3.6 Non-goals (+12 more)

### Community 138 - "ScriptedProvider"
Cohesion: 0.15
Nodes (6): FakeResearcher, Any, Synthesizes exactly one specific-enough niche, grounded in the fake evidence's…, Matches the CreatorResearcher Protocol CampaignResearchBatch accepts --…, ScriptedProvider, _Report

### Community 139 - "RunType"
Cohesion: 0.24
Nodes (15): What kind of research this run is (§11), distinct from RunScope, which…, RunType, InvalidResearchRunError, Exception, Validation for ResearchRun's run_type/reference invariants (§11). Enforces the…, validate_run_type(), _cosine(), ndarray (+7 more)

### Community 140 - "engine.py"
Cohesion: 0.13
Nodes (19): compute_hash(), compute_score(), Weighted mean of the components actually supplied. Normalise over the weight…, Deterministic hash: same inputs → same hash. Adapted from CIP Step 9., test_compute_hash_changes_with_input(), test_compute_hash_changes_with_rule_version(), test_compute_hash_deterministic(), test_compute_score_weighted_average() (+11 more)

### Community 141 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+11 more)

### Community 142 - "NicheQualifier"
Cohesion: 0.27
Nodes (18): NicheQualifier, AsyncSession, asyncio, AsyncSession, Integration tests for NicheQualifier against real Postgres., A verified niche without a promoted candidate still gets scored with zero…, Same inputs produce the same score on repeated runs., _setup_verified_niche() (+10 more)

### Community 143 - "PruneService"
Cohesion: 0.18
Nodes (14): PruneReport, PruneService, Any, AsyncSession, Maintenance ops — prune bulk history from Postgres to keep it bounded. The warm…, Deletes safe-to-drop bulk history older than a retention window. Dry-run by…, No-DB unit tests for the prune maintenance service., _session() (+6 more)

### Community 144 - "embed_texts"
Cohesion: 0.22
Nodes (11): embed_texts(), Embed a list of texts in batches. Returns an (N, EMBEDDING_DIM) float32 array., FakeEmbedder, ndarray, Unit tests for embeddings module — no model download needed., Deterministic embedder returning fixed-dimension vectors., test_embed_texts_basic(), test_embed_texts_batching() (+3 more)

### Community 145 - "WebPresenceAdapter"
Cohesion: 0.17
Nodes (6): _normalize(), AsyncClient, Collects a creator's landing page and its commerce-related outbound pages., GET ``url`` following redirects by hand so each hop is host-checked. Returns…, Stable id for a page: scheme+host+path, no query/fragment, max 255 chars., WebPresenceAdapter

### Community 146 - "._put"
Cohesion: 0.27
Nodes (4): _prep(), Any, Serialize JSON-typed values, datetime strings, and enum instances for SQLite., Table

### Community 147 - "compilerOptions"
Cohesion: 0.12
Nodes (16): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+8 more)

### Community 148 - "test_discovery_scan.py"
Cohesion: 0.05
Nodes (65): Any, Why a pass returned what it did — surfaced in the run record so a scan that…, A broad topic cleared to enter recursive discovery., SeedTopic, TrendScanStats, Evidence of demand and its direction over time., TrendProvider, build_momentum_provider() (+57 more)

### Community 149 - "ClusterPipeline"
Cohesion: 0.09
Nodes (28): ClusterPipeline, _cosine_to_centroid(), ndarray, Merge cluster labels into the creator's ContentItem.topics list. Produces a…, Cosine similarity of each row to the centroid, in [0, 1] (clipped)., Embeds ProblemObservations, clusters them, and persists results. A new run for…, FakeEmbedder, asyncio (+20 more)

### Community 150 - "schemas/niche.py"
Cohesion: 0.29
Nodes (10): CampaignNicheCreate, CampaignNicheDetailResponse, CampaignNicheResponse, BaseModel, NicheAliasCreate, NicheAliasResponse, NicheCreate, NicheDetailResponse (+2 more)

### Community 151 - "propose_ideas"
Cohesion: 0.25
Nodes (9): _as_price(), _evidence_supporting(), _normalize(), propose_ideas(), ProposedIdea, Any, Ask the provider for ideas grounded in ``texts``; keep only the ones whose…, Full-text (untruncated) superset match: every DISTINCT evidence row whose… (+1 more)

### Community 152 - "Decisions"
Cohesion: 0.13
Nodes (14): 1. Exclusion uses `NicheCandidateStatus.REJECTED`, not `policy_class`, 2. Only `AdapterFamily.NICHE` adapters fan out for topic queries, 3. Registry check: exact match against `Niche`/`NicheAlias`, 4. Multi-capability duplicate evidence: intentional two-lens persistence, 5. Evidence pool includes pre-existing rows, not just newly-inserted ones, 6. LLM provider is required, not optional, 7. Ungrounded synthesized niches are dropped, never given a fallback name, ADR-0033 — CORP1 Stage 5, T3: Recursive Niche Discovery Engine (+6 more)

### Community 153 - "ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator"
Cohesion: 0.13
Nodes (14): ADR-0036 — CORP1 Stage 5, T6: Dossier Model and Generator, Consequences, Context, Decisions, Evidence trail respects the Stage 4 acceptance test directly, Files changed, `generate_and_persist` is additive, not a replacement, `niche_id` comes from the caller, not auto-derived inside the generator (+6 more)

### Community 154 - "SourceHealthTracker"
Cohesion: 0.22
Nodes (5): BaseException, Path, Tracks adapter health and implements circuit-breaker logic. Usage:: tracker =…, SourceHealthTracker, test_save_and_load()

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

### Community 169 - "_make_session_factory"
Cohesion: 0.16
Nodes (12): _engine(), _LazySessionmaker, _make_session_factory(), async_sessionmaker, AsyncEngine, AsyncSession, Proxy that creates the real async_sessionmaker on first use., db_session() (+4 more)

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
Cohesion: 0.09
Nodes (16): AsyncSession, _as_int_or_none(), ChannelEnricher, NicheEcoResult, Any, Protocol, Search one niche and return every unique channel, uncorrected subscriber counts…, One deduplicated, batched subscriber-count lookup for the whole campaign,… (+8 more)

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

### Community 181 - "test_error_handlers.py"
Cohesion: 0.22
Nodes (9): _app(), FastAPI, No-DB tests for the API exception handlers., A request to an unregistered path triggers Starlette's base HTTPException (not…, A POST to a GET-only route triggers a 405 from Starlette's router., test_integrity_error_maps_to_409(), test_other_errors_still_500(), test_starlette_404_uses_error_handler() (+1 more)

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

### Community 217 - "app.py"
Cohesion: 0.10
Nodes (20): _close_quietly(), create_app(), _discovery_busy(), DiscoveryProviders, _job_busy(), _noop_close(), AsyncSession, FastAPI (+12 more)

### Community 218 - "Settings"
Cohesion: 0.08
Nodes (26): BaseSettings, Treat DISCOVERY_TOPICS_PER_PASS= (blank) as unset. .env files carry everything…, Settings, _configured_members(), _gemini(), _groq(), Provider selection — builds the configured LLMProvider from settings. Selection…, build_fair_provider() (+18 more)

### Community 219 - "test_coerce.py"
Cohesion: 0.31
Nodes (9): _provider(), parametrize, Unit tests for defensive LLM-output coercion + parse-path regressions., test_as_bool(), test_as_float(), test_as_int(), test_creator_content_survives_bad_values(), test_extraction_survives_bad_confidence_and_bool() (+1 more)

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

### Community 234 - "SourceHealthRecord"
Cohesion: 0.36
Nodes (4): Any, SourceHealthRecord, test_record_from_dict_ignores_extra_keys(), test_record_roundtrip()

### Community 235 - "test_discovery_endpoint.py"
Cohesion: 0.07
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
Nodes (18): _cfg(), fixture, Install a fake ``fair.embedded.module.FAIR`` class for build_fair_provider to…, Fake FAIR that accepts CORP's full kwarg set., An installed FAIR that doesn't accept ``env_file`` should be retried without…, Signature so different that no kwargs match — must raise FairUnavailableError…, A FAIR that reads a bad env file at construction, or otherwise raises, should…, FAIR constructs fine, then ``router.providers()`` blows up (e.g. an older… (+10 more)

### Community 242 - "score_solution_saturation"
Cohesion: 0.33
Nodes (6): Higher = less saturated = more room, from SolutionProvider evidence…, score_solution_saturation(), test_solution_saturation_at_cap_fully_saturated(), test_solution_saturation_beyond_cap_stays_zero(), test_solution_saturation_few_solutions_high_score(), test_solution_saturation_no_evidence_is_neutral()

### Community 243 - "is_public_url"
Cohesion: 0.33
Nodes (6): is_public_url(), All addresses ``host`` resolves to. Module-level so tests can stub it., True only for http(s) URLs whose host resolves solely to public addresses.…, _resolve_host(), parametrize, test_is_public_url_rejects_internal_and_non_http()

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
Cohesion: 0.09
Nodes (45): DiscoveryConfig, AsyncSession, RuntimeError, Turns the broad-topic catalogue into a ranked list of seed topics.…, Best-effort momentum score per topic. Missing keys mean no signal, which the…, No live momentum signal, and the catalogue forbids rotation fallback., Pull a 0..100 momentum score out of whatever the adapter returned. The YouTube…, The ``scan:`` block of rules/broad_topics.yaml, plus its topics. (+37 more)

### Community 271 - "collector.py"
Cohesion: 0.12
Nodes (30): embedding_to_bytes(), _get_store(), mirror_content_items(), mirror_evidence(), mirror_interactions(), mirror_metrics(), mirror_observations(), mirror_research_queries() (+22 more)

### Community 275 - "mock_session"
Cohesion: 0.67
Nodes (3): mock_session(), fixture, tracker()

### Community 277 - "._get_engine"
Cohesion: 0.24
Nodes (5): AsyncEngine, Return {id: raw_text} for the given evidence IDs., Return {id: embedding_bytes} for the given observation IDs., Return {table_name: row_count} for every warm table., Create all warm-store tables (idempotent), then heal column drift.…

### Community 278 - "LLMProvider"
Cohesion: 0.09
Nodes (11): AsyncSession, AsyncSession, AsyncSession, AsyncSession, PooledProvider, Any, LLMProvider, Abstract LLM provider with JSON-mode generation. (+3 more)

### Community 279 - "jobs.py"
Cohesion: 0.30
Nodes (13): _close(), _commit_or_rollback(), _embedder_factory(), Any, In-process background jobs for long-running pipelines. The console needs to…, Persist whatever a crashing pipeline flushed (e.g. a failed ResearchRun). If…, Run one stage. ``collect`` needs platform + identifier., One autonomous discovery pass (CORP1 Step 1, Level 0 onwards). With no… (+5 more)

### Community 283 - "CompetitorStrength"
Cohesion: 0.29
Nodes (10): CompetitorStrength, str, Higher = more whitespace (less saturated), matching the "higher is better"…, score_competitor_saturation(), test_competitor_saturation_above_cap_clamped(), test_competitor_saturation_empty_list_neutral(), test_competitor_saturation_fully_saturated(), test_competitor_saturation_mixed() (+2 more)

### Community 284 - "patched_pipeline"
Cohesion: 0.25
Nodes (7): _FakeRun, patched_pipeline(), discover(), qualify_campaign(), fixture, Replace the drill engine and qualifier so these tests exercise the pass's own…, discover()

### Community 285 - "score_audience_dissatisfaction"
Cohesion: 0.33
Nodes (6): From DissatisfactionProvider evidence — low-star reviews, complaints about…, score_audience_dissatisfaction(), test_audience_dissatisfaction_at_cap(), test_audience_dissatisfaction_higher_is_stronger_signal(), test_audience_dissatisfaction_positive(), test_audience_dissatisfaction_zero_evidence()

## Knowledge Gaps
- **625 isolated node(s):** `corp`, `FakeCluster`, `FakeOppScore`, `FakeObservation`, `$schema` (+620 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 2001 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **61 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `NormalizedContent` connect `NormalizedContent` to `MultiSourceDiscovery`, `ComplianceStatus`, `niche_discovery.py`, `YouTubeAdapter`, `collector.py`, `models/evidence.py`, `WebPresenceAdapter`, `test_niche_discovery.py`, `test_discovery_scan.py`, `ProblemCluster`, `YouTubeTrendsAdapter`, `MarketplaceAdapter`, `ResearchRun`, `AmazonReviewAdapter`, `PatreonSubstackAdapter`, `AppStoreAdapter`, `StackExchangeAdapter`, `test_capabilities.py`, `CrowdfundingAdapter`, `GoogleTrendsAdapter`, `WikipediaAdapter`, `build_adapter`, `SearchDemandAdapter`, `HackerNewsAdapter`, `test_discovery.py`, `RedditAdapter`, `test_multi_discovery.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `LLMProvider` connect `LLMProvider` to `ComplianceStatus`, `ResearchOrchestrator`, `test_fair_provider.py`, `CompetitivePipeline`, `niche_discovery.py`, `IntelligencePipeline`, `ScriptedProvider`, `RunType`, `test_intent_classifier.py`, `test_trend_scan.py`, `extract_observations`, `test_intent_pipeline.py`, `providers/registry.py`, `test_niche_discovery.py`, `classify_topics`, `test_discovery_scan.py`, `Embedder`, `propose_ideas`, `ProblemCluster`, `build_provider`, `test_intelligence_pipeline.py`, `ResearchRun`, `intelligence/errors.py`, `ProviderExhaustedError`, `app.py`, `Settings`, `lifespan`, `test_niche_candidates.py`, `test_product_ideation.py`, `test_niche_naming.py`, `test_groq_provider.py`, `LLMCallError`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `ComplianceStatus` connect `ComplianceStatus` to `CompetitivePipeline`, `test_endpoints.py`, `Niche`, `YouTubeAdapter`, `test_intent_pipeline.py`, `models/evidence.py`, `WebPresenceAdapter`, `test_youtube_trends_adapter.py`, `test_niche_discovery.py`, `ClusterPipeline`, `NormalizedContent`, `ProblemCluster`, `YouTubeTrendsAdapter`, `MarketplaceAdapter`, `test_intelligence_pipeline.py`, `ResearchRun`, `AmazonReviewAdapter`, `PatreonSubstackAdapter`, `AppStoreAdapter`, `StackExchangeAdapter`, `test_capabilities.py`, `test_watch_rescanner.py`, `CrowdfundingAdapter`, `GoogleTrendsAdapter`, `WikipediaAdapter`, `test_registry_rescan.py`, `test_web_adapter.py`, `build_adapter`, `SearchDemandAdapter`, `HackerNewsAdapter`, `test_corp2_export.py`, `test_niche_candidates.py`, `test_discovery.py`, `test_product_ideation.py`, `test_stage4_models.py`, `RedditAdapter`, `test_dossier_persistence.py`, `test_multi_discovery.py`, `NicheLifecycleStatus`, `test_niche_canonicalization.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `NormalizedContent` (e.g. with `AcquisitionCollector` and `_is_interaction()`) actually correct?**
  _`NormalizedContent` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `ResearchRun` (e.g. with `_mark_orphaned_runs()` and `get_evidence()`) actually correct?**
  _`ResearchRun` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 88 inferred relationships involving `ComplianceStatus` (e.g. with `create_evidence()` and `EvidenceCreate`) actually correct?**
  _`ComplianceStatus` has 88 INFERRED edges - model-reasoned connections that need verification._
- **Are the 88 inferred relationships involving `AccessMethod` (e.g. with `create_evidence()` and `EvidenceCreate`) actually correct?**
  _`AccessMethod` has 88 INFERRED edges - model-reasoned connections that need verification._