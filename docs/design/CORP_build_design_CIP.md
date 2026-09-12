# CORP — CIP-Driven Build Design (Claude Code handoff) — v1.1

**Input:** CORP Product & System Specification v1.0
**Method:** CIP capability decomposition + search-before-build, applied to CORP's build.
**Verification date:** 2026-09-11 (re-verify items marked *[verify]* at build time).
**v1.1 change:** the search-before-build gate was executed against five candidate public repos (new §3); acquisition and build-sequence sections updated with what it found.

---

## 0. What "using CIP" means here

Your CIP instance runs locally and its project/requirements/fit-eval API (Step 14) isn't live yet, so I couldn't feed CORP through the running system. Instead I applied CIP's **method** to CORP:

1. **Unit of value is the capability, not the repository** — decompose CORP into discrete capabilities.
2. **Search before build** — for each capability, ask what public implementation already exists (now partly executed, §3).
3. **Six verdicts** — Adopt / Adapt / Wrap / Reference / Reject / **Build**. Build is the last resort, only where search fails.

The single most important output: **CORP is ~70% assembly + reuse of CIP's own subsystems, and ~30% genuinely new code.** If you build it as if it's all new, you'll spend months re-solving problems you already solved in CIP.

When CIP Step 14 ships, CORP's capability list below *is* a valid CIP `project` + `requirements` definition (see `corp_cip_project.yaml`) — feed it in and let CIP produce the real recommendations pinned to exact revisions. This doc is the manual first pass.

---

## 1. Two findings before you build

### Finding 1 — Acquisition reality collapses your platform list to YouTube (verified today)

The spec targets YouTube, Instagram, TikTok, Reddit, Facebook. CORP's actual data need is *the audience comments/questions of creators who have not opted in and don't know you exist*. Against that specific need:

| Platform | Status for CORP's need | Verdict |
|---|---|---|
| **YouTube** | Public comment threads + video metadata via official Data API v3, **no creator consent required**. ~10,000 quota units/day default; `search.list` = 100 units, but `commentThreads.list` is cheap. Fine for one niche. | **Viable v1 channel** |
| **Reddit** | Public subreddit problems, official API. But access/pricing tightened hard in 2023 — *[verify current terms + cost]*. | Viable #2, verify first |
| **Instagram** | Graph API only returns data for accounts **you own or that consent** (Business/Creator + FB Page + app review). Basic Display deprecated Dec 2024. | Official = reject; **vendor scrape possible** (§2) |
| **TikTok** | Research API is **closed to commercial users** (academic/non-profit only). | Official = reject; **vendor scrape possible** (§2) |
| **Unified APIs (Phyllo etc.)** | Normalized multi-platform data — but **creator-consented**: the creator connects their own account via SDK. Wrong model for researching strangers. | **Reject for v1** (relevant *after* partnership, not before) |

**This is the correct scope cut, not a limitation to paper over.** Your spec's Source Adapter abstraction (§5, §12) earns its keep precisely because it lets every non-YouTube adapter stay a stub while the intelligence layer works end-to-end on one real source. Phase 0 ("prove reliable acquisition for at least one primary platform") passes cleanly with YouTube.

### Finding 2 — CORP automates the step that isn't your bottleneck (the real challenge)

CORP automates **discovery**. But the binding constraint on the whole venture is **outreach conversion** — will a creator agree to a revenue split with a stranger? Your own record says cold outreach is the hard part, which is why you designed the gated "golden-nugget-first" approach.

A better, larger lead list does not fix a conversion problem. If you can't convert one creator you researched by hand in a weekend, a machine that finds 500 doesn't help — it industrialises a step that isn't the constraint, and defers the test that actually matters.

CORP's own §19 preaches "validate demand before the expensive build." Turn that on CORP itself: **the cheap experiment sits before the expensive one.** The cheap experiment is one dossier on one real creator, used to test whether a dossier-backed pitch changes your conversion.

**Recommendation:** don't have Claude Code build all 9 phases yet. Two ways to run the cheap experiment first, cheapest first:

- **(a) Zero-build validation — do this first.** Install the `social-media-research-ops` skill (§3, repo #2) into Claude Code and run the manual research on **one creator you already have in mind** this week. It produces a dossier-shaped output into Obsidian with no code written. If that dossier moves your outreach, proceed to (b); if not, you've spent an afternoon instead of months.
- **(b) Thin vertical slice** (§6) — YouTube → collect → extract → cluster → intent → one dossier → Gate A, for that same creator. Reuses CIP's subsystems, so it's cheap, and it's the productised version of what (a) proved by hand.

The decision "full build vs. validate-then-thin-slice" is the one real fork here. Make it on purpose.

---

## 2. Capability decomposition + reuse verdicts

CORP's 16 modules decompose into ~24 capabilities. Grouped by layer, with the CIP verdict and candidate. **Build** items are deliberately tiny.

### Foundation
| Capability | Verdict | Candidate / note |
|---|---|---|
| Relational DB + migrations | **Adopt** | Postgres 16 + Alembic — same as CIP. Copy CIP's scaffold. |
| Config / settings | **Adopt** | pydantic-settings (CIP stack). |
| Job scheduler / rate limits / retries / incremental refresh | **Wrap** | `arq` (async) or Celery+Redis. **Do not build a scheduler.** Retries → `tenacity`; rate limits → `pyrate-limiter`. |
| API layer | **Adopt** | FastAPI (CIP stack). |
| Review console frontend | **Adopt** | React + Vite + shadcn/ui + TanStack Table. Reference your TCF frontend patterns. |
| Repo discipline (core/ ⊥ workers/, migration→core→worker→tests, bug-injection pass) | **Adopt (your own)** | Copy CIP's import-linter contracts and per-step discipline verbatim. |

### Source acquisition — **two adapter families**

Split the adapter layer in two. Most of the audience-problem signal does **not** have to come from a specific creator's comment section — it lives, keyed to a *niche*, in open sources with no access problem. You only strictly need creator-bound comments for the *binding* step (which creator's audience has which problem).

**Family 1 — Creator-bound adapters** (whose audience it is):

| Capability | Verdict | Candidate / note |
|---|---|---|
| YouTube adapter (channel resolve, video list, comment threads) | **Wrap** | `google-api-python-client`. Official, no consent, the v1 binding source. |
| YouTube transcripts/captions | **Adopt** | `youtube-transcript-api`. |
| IG / TikTok / FB / X comment collection | **Wrap (vendor)** — *not* Build | **Two vendor routes** (compare, §3): Apify actors (TikTok comments ≈ $0.50/1K, IG ≈ $1.50/1K, YouTube ≈ $2.40/1K), or **ScrapeCreators** (repo #1) which bundles pre-built research *skills* on top of the scrape API. **Risk flags:** breaches platform ToS, undocumented endpoints (break on layout change), comments are PII (copyright + GDPR/TT-DPA). Accept deliberately; defer past v1. |
| Reddit adapter (creator's own subreddit/community) | **Wrap** | `PRAW`, or Apify Reddit actor (≈ $4/1K, rental) — *[verify current API terms/cost]*. |

**Family 2 — Niche-signal adapters** (creator-agnostic problem reservoirs, mostly open — often *higher* quality than a creator's IG comments):

| Capability | Verdict | Candidate / note |
|---|---|---|
| Search-demand mining (real purchase-intent questions) | **Wrap** | Google autocomplete / "People Also Ask" / Trends via `pytrends` (free). Demand keyed to niche, zero access problem. |
| Amazon review mining (unmet need + competitor weakness) | **Wrap** | 1–3★ reviews = pure §8 Solution-Research + commercial-intent data. Public. |
| Stack Exchange (technical/how-to niches) | **Adopt** | Fully open API; questions *are* audience problems. |
| Marketplace listings + reviews (what already sells) | **Wrap** | Gumroad / Etsy / Udemy — validates §8 saturation + pricing. |

| Cross-cutting | Verdict | Candidate / note |
|---|---|---|
| Normalized adapter output schema (one schema, both families) | **Build** (small) | CORP-specific. The one genuinely-new acquisition-layer artifact. A pydantic model, not a framework. Carries per-source `compliance_status` + `access_method` (official / vendor-scrape / open) so the confidence and governance layers can read it. |

**Consented-data providers (Phyllo etc.) are deliberately excluded from discovery** — they require the creator to connect their own account, the wrong model for researching strangers. Relevant only *after* partnership (Gate C+).

### Intelligence
| Capability | Verdict | Candidate / note |
|---|---|---|
| Topic / content classification | **Wrap** | Gemini free tier (your CIP provider) + structured output. |
| Audience problem/question extraction | **Wrap** | Gemini + `instructor`/pydantic structured extraction → `ProblemObservation` rows, each FK'd to `Evidence`. **Reference the extraction prompts** in repos #1 (`comment-mining`) and #2 (§3) rather than writing from scratch. |
| Embeddings | **Adopt** | `sentence-transformers` (all-MiniLM) local = zero marginal cost. Fits your free-tier bias. |
| Problem clustering (embed→cluster→label) | **Adopt / Adapt** | **`BERTopic`** collapses most of stages 4–6 (embed → HDBSCAN → topic labels). Strongest single reuse hit. Fallback: `HDBSCAN` + scikit-learn. The one capability worth a real compare (§8). |
| Vector storage | **Adopt** | `pgvector` — stays inside Postgres, no new infra. |
| Commercial-intent classification | **Wrap** | Gemini classifier over the signal hierarchy. |
| Commercial-intent signal hierarchy (weak/moderate/strong/validation) | **Build** (tiny) | A rules table. CORP §9. |
| Market/solution research (existing products, pricing) | **Wrap** | A web-search API (Tavily / Brave / SerpAPI). Phase 5+. |

### Scoring, evidence, workflow — **this is where CIP reuse dominates (see §4)**
| Capability | Verdict | Candidate / note |
|---|---|---|
| Evidence & provenance model | **Adapt (CIP)** | CIP's `evidence_item` + FK-traceable claims (Step 12). |
| Deterministic, reproducible scoring | **Adapt (CIP)** | CIP Step 9 byte-stable `computed_hash`. |
| Declarative scoring weights / decision rules | **Adapt (CIP)** | CIP Step 12 YAML decision rules — CORP §7 weights drop straight in. |
| Confidence banding | **Adapt (CIP)** | CIP EOR banding pattern → CORP §8 confidence. |
| Automation-boundary gates (Gate A–E) | **Adapt (CIP)** | CIP policy gates (Step 10) + publication guards (Step 11) + append-only override pattern. |
| LLM provider routing (deterministic, free-tier-first) | **Adapt/Reference (CIP)** | CIP Provider Registry + Judgment Orchestrator + OD-16 deterministic routing. |
| State machine (18 states) | **Adapt (CIP)** | CIP's state-machine/workflow spec pattern; or `python-statemachine`. |
| "LLM output is never a source" invariant | **Reference (CIP)** | Identical principle to CIP — same lineage. |

### Presentation
| Capability | Verdict | Candidate / note |
|---|---|---|
| Dossier rendering | **Wrap + Build** | Jinja2 engine (Adopt) + CORP dossier template (Build). Optionally render via your docx/pdf skills. |
| Human Review Console | **Adopt** | Mirror CIP Step 14 (FastAPI read/write + minimal React). |

**Net Build surface for v1:** normalized adapter schema, the commercial-intent rules table, the dossier template, and wiring. Everything else is Adopt (public libs), **Adapt-from-your-own-CIP**, or now **Reference-from-existing-skills** (§3).

---

## 3. Prior art — five candidate repos (search-before-build gate, executed)

Evaluated 2026-09-11. This is the gate doing its job: two of these can replace parts of what you'd otherwise build, as **installable skills**, not code you write.

| Repo | What it is | Verdict for CORP |
|---|---|---|
| **ScrapeCreators/social-media-research-skills** | 12 Claude Code Agent Skills (`comment-mining`, `product-demand-research`, `audience-research`, `influencer-prospecting`, `creator-profile-teardown`, `transcript-intelligence`…) wrapping the paid **ScrapeCreators** scrape API. Python, `npx skills add`. Principles mirror CORP (public-data only, cited outputs, exact-language). | **Wrap (vendor) + Adopt (skills).** Third acquisition-vendor option beside Apify — reaches TikTok/IG comments official APIs won't (same ToS+PII risk). Its analysis skills can stand in for parts of Steps 3–5. *Verify ScrapeCreators pricing/coverage vs Apify before committing.* |
| **HunterSUNSUN/social-media-research-ops** | A Claude Code/Codex **methodology skill** (markdown, not code): evidence-based competitor + comment research written into **Obsidian**. Three-layer creator map incl. fast-growing small accounts = your 10K–200K band. Comments as first-class demand signal; observed-vs-inference separation; read-only. | **Adopt (as skill, now) + Reference.** This *is* the manual N=1 validation workflow from Finding 2 — installable today, Obsidian-native (fits Ricky OS). Browser-driven / read-only / low-volume → validation pass, not a scale engine. **Start here.** |
| **skainguyen1412/social-media-research-skill** | Node/TS CLI + skill; Reddit/X opinion analysis (rank/sentiment/trend/controversy/discovery), structured JSON + visualize dashboard, quotes-as-evidence. | **Reference only.** Good for the analysis-type taxonomy, the console dashboard, and quotes-as-evidence. TypeScript (CORP is Python); needs OpenAI+xAI keys (not free-tier); topic-oriented not creator-oriented. Read, don't take code. |
| **kushalsamani/social-media-ai-agent** | CrewAI multi-agent: research→strategy→calendar→posts→SEO. Gemini + Serper + Pydantic structured outputs; JSON→Markdown renderer. | **Reference (narrow) — and downstream.** It's *content generation* (golden-nugget / Steelpan phase), not research. Reference only the Gemini+Serper+Pydantic wiring + renderer. **CrewAI = model-orchestrated multi-agent → against your OD-16;** don't copy the architecture. |
| **clankwright/spam-bot-3000** | Mass-promotion spam bot: scrape + auto-reply/DM/follow, with built-in anti-detection evasion. | **Reject.** Opposite of CORP's founding principle (no auto-contact; automate research, not accountability). Abusive, ToS-violating, reputation-destroying, gets accounts banned. Do not integrate. |

**Cautions the gate surfaces:** (a) repos #1, #3, #4 all pull you onto paid third-party APIs (ScrapeCreators / OpenAI+xAI / Serper) — fine for validation, against your free-tier posture at scale, so choose the acquisition vendor deliberately (YouTube-official vs Apify vs ScrapeCreators). (b) These are new, low-star repos (5–11 commits, except the spam bot) — trust the *skills and prompts* you can read in an afternoon, not the *code* as a long-term dependency.

---

## 4. The headline: CORP and CIP share DNA

Both systems are evidence-first, human-gated, deterministic-scoring, free-tier-LLM research engines. CIP researches *code capabilities*; CORP researches *creator/audience problems*. The plumbing is the same. Concretely, lift from CIP:

- **Evidence architecture** (Step 12): append-only, every material claim FK'd to an evidence row. CORP §8 is this, verbatim.
- **Deterministic reproducible scoring** (Step 9): CORP §7/§8 require "reproducible from stored component scores" — that *is* `computed_hash`.
- **Declarative YAML decision rules** (Step 12): CORP's §7 weight table and recalibration story is a rules file, not hardcoded logic.
- **Gates + append-only overrides** (Steps 10–11): CORP's Gate A–E are policy gates with recorded rationale.
- **Deterministic provider routing** (OD-16): CORP's LLM calls should route deterministically, same as CIP, for auditability.
- **Repo discipline**: `core/` never imports `workers/`, migration→core→worker→tests, bug-injection verification pass.

Treat CORP's scoring/evidence/workflow core as **a re-skin of CIP's**, not a new build. That alone removes the hardest, most bug-prone third of the system.

---

## 5. Repo skeleton (respects your import-linter discipline)

```
corp/
  core/                      # pure domain logic — NEVER imports workers/
    models/                  # pydantic + SQLAlchemy entities (§10)
    scoring/                 # deterministic scoring + computed_hash  (Adapt CIP)
    evidence/                # provenance model                       (Adapt CIP)
    rules/                   # YAML decision rules + loader            (Adapt CIP)
    intent/                  # commercial-intent hierarchy (rules)     (Build)
    state/                   # state machine (§11)                     (Adapt CIP)
  workers/
    adapters/                # source adapters (common output schema)
      youtube.py             # Wrap google-api-python-client (v1)
      base.py                # normalized adapter interface            (Build)
    acquisition/             # scheduler, rate limits, retries         (Wrap arq/tenacity)
    intelligence/            # LLM extraction + BERTopic clustering
    research/                # market/solution web research            (Phase 5+)
    providers/               # LLM provider registry + routing         (Adapt CIP)
    dossier/                 # Jinja2 dossier generator
  api/                       # FastAPI read/write                      (mirror CIP Step 14)
  web/                       # React + Vite review console
  migrations/                # Alembic
  rules/                     # *.yaml — scoring weights, eligibility, intent
  tests/                     # pytest against real Postgres 16
  pyproject.toml             # import-linter contracts, PYTHONHASHSEED=random
```

---

## 6. Recommended v1 build sequence (thin slice, N=1, YouTube-only)

**Pre-step (zero code):** install `social-media-research-ops` (repo #2), optionally `ScrapeCreators/comment-mining` (repo #1), and run the manual research on one creator. Confirm the dossier is worth productising **before** writing Step 0. (Finding 2.)

Then, per your discipline: migration → core domain → worker → pytest against real Postgres → bug-injection pass. Before writing any **Build** module, run the search-before-build check (`CORP_search_before_build_checklist.md`).

- **Step 0 — Scaffold.** Copy CIP's skeleton: Postgres 16 + Alembic, `core/ ⊥ workers/` import-linter contract, pydantic-settings, pytest harness, `PYTHONHASHSEED=random`. *(Adopt your own.)*
- **Step 1 — Core data model.** `Creator`, `CreatorPlatformAccount`, `ContentItem`, `AudienceInteraction`, `Evidence`, `ResearchRun`. Migration + core + tests. *(Adapt CIP evidence model.)*
- **Step 2 — YouTube adapter.** Given a channel handle: resolve channel → list videos → pull public comment threads → pull captions. Emit the normalized schema. Wrap quota/rate limits (tenacity + pyrate-limiter). Store with provenance. **Manual creator input — no discovery yet.**
- **Step 3 — Content + audience intelligence.** LLM extraction (Wrap Gemini, structured output): topic classification; per-comment problem/question/pain → `ProblemObservation`, each FK'd to `Evidence`. Enforce observed-vs-inferred (§8). **Reuse the extraction prompts from repos #1/#2 as your starting point.**
- **Step 4 — Problem clustering.** Embed `ProblemObservation`s (sentence-transformers, local) → BERTopic/HDBSCAN → `ProblemCluster` with frequency/recency/evidence-strength + representative evidence. Store in pgvector.
- **Step 5 — Commercial intent.** Rules table (weak/moderate/strong/validation) + LLM classification → `CommercialSignal` FK'd to `Evidence`.
- **Step 6 — Scoring + confidence.** Deterministic component + aggregate scores, reproducible `computed_hash`; YAML weights (§7); confidence banding. Persist with rule/model version. *(Adapt CIP Steps 9 + 12.)*
- **Step 7 — Dossier.** Jinja2 template → the §13 dossier for the single creator, with evidence drill-down references. *(Optionally render via docx/pdf skill.)*
- **Step 8 — Minimal console + Gate A.** FastAPI read API + minimal React page: dossier + evidence drill-down + Approve/Reject/Watch, recording `HumanDecision`. *(Mirror CIP Step 14.)*

**Deferred to full CORP (only if the slice earns it):** discovery/eligibility automation (Phase 2), identity resolution, deep-research second pass (Phases 7/12), feedback-loop recalibration (Phase 8), cross-niche discovery (Phase 9), and vendor-scraped IG/TikTok/Reddit/FB adapters.

---

## 7. Phase 0 source-capability matrix (pre-filled — don't restart from zero)

| Source | Family | Access method | Consent | Cost | ToS/legal | v1? |
|---|---|---|---|---|---|---|
| YouTube Data API v3 | Creator-bound | Official | No | Free ~10k units/day | Compliant | **Yes** |
| Reddit (creator community) | Creator-bound | Official / vendor | No | ≈$4/1K vendor *[verify]* | *[verify]* | Maybe #2 |
| IG / TikTok / FB / X comments | Creator-bound | **Vendor scrape** (Apify *or* ScrapeCreators) | No | ≈$0.50–2.40/1K | **ToS breach + PII** | Post-v1, accept risk |
| Instagram Graph (official) | Creator-bound | Official | Yes (own/consented) | Free | Compliant | No — wrong model |
| TikTok Research (official) | Creator-bound | Official | Academic only | — | Closed to commercial | No |
| Search demand (autocomplete/PAA/Trends) | Niche-signal | Open | No | Free | Compliant | Cheap add |
| Amazon reviews | Niche-signal | Open/scrape | No | Low | Public | Strong add |
| Stack Exchange | Niche-signal | Official | No | Free | Compliant | If technical niche |
| Gumroad/Etsy/Udemy | Niche-signal | Open/scrape | No | Low | Public | Phase 5 |
| Phyllo (unified) | — | Consented SDK | Yes | Paid | Compliant, wrong model | Only post-partnership |

Every adapter emits `compliance_status` + `access_method`; the confidence layer lowers confidence for narrow/single-source coverage and the governance layer (PDR revision #5) reads these fields.

**Re-verify at build time:** Reddit API terms + cost; current Apify / ScrapeCreators actor availability + pricing; YouTube quota for your call pattern; Gemini free-tier limits + ToS.

---

## 8. Open decisions for you

1. **Full build vs. validate-then-thin-slice** (Finding 2). The one real fork. Recommendation: run the zero-build validation (repo #2) first.
2. **Acquisition vendor:** YouTube-official only (v1) vs Apify vs ScrapeCreators for the creator-bound scrape layer. Compare coverage, price, and ToS posture before wiring past v1.
3. **Feed CORP into CIP once Step 14 ships?** CORP is a clean first real CIP project — closes CIP's loop and pins these verdicts to exact revisions.
4. **BERTopic vs. hand-rolled embed+cluster.** BERTopic is the higher-leverage Adopt; confirm it fits your determinism bar (model-version sensitivity — pin versions).
5. **Reddit as v1 #2** or defer until the YouTube slice proves the pipeline.

---

## 9. Recommended PDR revisions (CORP spec v1.0 → v1.1)

The v1.0 spec is strong — evidence-first, human-gated, well-modelled. These are the gaps a challenger read surfaces. **First-order** items change whether CORP works or wastes money.

### First-order
1. **Add a Cost & Throughput Budget (missing entirely).** A system that researches "thousands of creators" states no cost-per-creator or cost-per-dossier. Define both, and design the pipeline to spend *cheaply on the many* (free-tier LLM, local embeddings, cached extraction) and *expensively only on the ranked few* (deep research). CIP is built on free-tier-first discipline; CORP inherits none of it explicitly. Without this you can burn real money across 5,000 creators before a single partnership.

2. **Add an Evaluation Harness / ground-truth seed (missing "definition of good").** §8 prevents fabricated *evidence* but nothing prevents a well-evidenced but *wrong* opportunity score — and you won't know until real outcomes arrive months later. Fix: hand-rank 15–20 creators, and require CORP's ranking to correlate with your judgment on that seed *before* you trust its scores.

3. **Elevate cross-creator problem aggregation (buried in Phase 9).** The strongest signal is "this problem recurs across 40 creators' audiences," not "within one creator." §6 clusters only *within* a creator. Make `ProblemCluster` span creators and treat cross-creator recurrence as a top-tier evidence signal.

4. **Cap human-review throughput (the human is the real bottleneck).** Per Finding 2, if CORP produces 50 dossiers/week and you review 5, the queue explodes and the output is wasted. Cap dossiers reaching the human to top-N per period; auto-watchlist/expire the rest. Design the funnel around your actual review capacity.

5. **Add a Data Governance & Compliance section (currently scattered across §12/§19).** Comments are PII; record per-source `compliance_status` and `access_method`; state retention/deletion posture and ToS stance per adapter; record any vendor-scrape risk acceptance in an append-only log (reuse CIP's `risk_acceptance` pattern). One section, not footnotes.

### Secondary
6. **Split `CreatorScore` vs `OpportunityScore` in the data model.** §7 says score them separately but §10 has a single `Score` entity. Rank *opportunities* primarily so a small creator with a great problem outranks a big creator with none.
7. **Add a recency / demand-trend dimension.** Three-year-old comments aren't current demand. Weight recent signal higher; distinguish "was hot" from "is hot."
8. **Add a disqualifiers ruleset + "creator already sells this" check.** Blacklist/disqualify criteria (saturated creator, audience hostile to selling) prevent wasting deep-research budget; before proposing a `ProductConcept`, cross-check the creator's existing offers so you never pitch what they already sell.
9. **Pin the extraction-prompt version per `ResearchRun`.** The comment→`ProblemObservation` prompt is the biggest hallucination surface. Version it alongside model/rule versions so any re-run is auditable.
10. **Add calibration governance.** §16 says recalibrate weights against outcomes but not how. Freeze weights until a minimum outcome sample exists — guard against overfitting on N=3.
