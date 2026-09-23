export type CreatorStatus = string;

export interface Paged<T> {
  items: T[];
  totalCount: number;
}

export interface PlatformAccount {
  id: string;
  creator_id: string;
  platform: string;
  handle: string;
  external_id: string | null;
  subscriber_count: number | null;
  verified: boolean;
}

export interface Creator {
  id: string;
  name: string;
  niche: string | null;
  discovery_source: string | null;
  status: CreatorStatus;
  notes: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatorDetail extends Creator {
  platform_accounts: PlatformAccount[];
}

export interface PlatformAccountCreateInput {
  platform: string;
  handle: string;
  external_id?: string | null;
}

export interface CreatorCreateInput {
  name: string;
  niche?: string | null;
  discovery_source?: string | null;
  notes?: string | null;
  accounts: PlatformAccountCreateInput[];
}

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface Job {
  id: string;
  kind: string;
  creator_id: string | null;
  campaign_id: string | null;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

export type CampaignStatus = "draft" | "active" | "paused" | "completed";

export interface Campaign {
  id: string;
  name: string;
  status: CampaignStatus;
  research_profile_version: string | null;
  target_niche_count: number;
  initial_creators_per_niche: number;
  creator_min_followers: number;
  creator_max_followers: number;
  human_gate_capacity: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignCreateInput {
  name: string;
  research_profile_version?: string | null;
  target_niche_count?: number;
  initial_creators_per_niche?: number;
  creator_min_followers?: number;
  creator_max_followers?: number;
  human_gate_capacity?: number;
}

export type CampaignNicheStatus =
  | "discovered"
  | "candidate"
  | "canonical"
  | "verified"
  | "qualified"
  | "selected"
  | "rejected";

export interface CampaignNiche {
  id: string;
  campaign_id: string;
  niche_id: string;
  discovery_rank: number | null;
  qualification_score: number | null;
  confidence: number | null;
  research_completeness: number | null;
  creator_count_observed: number;
  target_band_creator_count: number | null;
  status: CampaignNicheStatus;
  selected: boolean;
  rationale: string | null;
  created_at: string;
  updated_at: string;
  niche?: Niche;
}

export interface Niche {
  id: string;
  canonical_name: string;
  description: string | null;
  parent_domain: string | null;
  policy_class: string | null;
  lifecycle_status: string;
  created_at: string;
  updated_at: string;
}

export interface SignalSummary {
  signal_level: string;
  confidence: number | null;
  rationale: string | null;
}

export interface OpportunityScore {
  id: string;
  creator_id: string;
  problem_cluster_id: string;
  component_scores: Record<string, number>;
  aggregate_score: number;
  confidence_band: string | null;
  diagnostics: Record<string, unknown> | null;
}

export interface ClusterDetail {
  id: string;
  creator_id: string | null;
  label: string | null;
  description: string | null;
  frequency: number | null;
  recency_score: number | null;
  evidence_strength: number | null;
  member_count: number;
  signal: SignalSummary | null;
  score: OpportunityScore | null;
}

export interface ProblemObservation {
  id: string;
  evidence_id: string;
  text: string;
  category: string | null;
  is_inferred: boolean;
  // Post-integration fields from the merged tier2 + niche-discovery pipelines.
  sentiment?: "positive" | "neutral" | "negative" | null;
  urgency?: "low" | "medium" | "high" | null;
  source_side?: "audience" | "creator";
}

export type CompetitorType = "direct" | "substitute" | "diy_workaround";
export type CompetitorStrength = "weak" | "moderate" | "strong";

export interface Competitor {
  id: string;
  problem_cluster_id: string;
  name: string;
  competitor_type: CompetitorType;
  strength: CompetitorStrength;
  url: string | null;
  gap_notes: string | null;
  evidence_id: string | null;
}

export interface Decision {
  id: string;
  creator_id: string;
  opportunity_score_id: string | null;
  decision: string;
  rationale: string | null;
  decided_at: string;
  decided_by: string | null;
  gate: string;
}

export interface ResearchRun {
  id: string;
  creator_id: string | null;
  scope: string;
  status: string;
  // Null until the run actually starts (ResearchRunResponse.started_at is optional).
  started_at: string | null;
  completed_at: string | null;
  stats: Record<string, unknown> | null;
}

export interface CommercialSignal extends SignalSummary {
  id: string;
  problem_cluster_id: string;
  evidence_id: string;
  classification_model: string;
  prompt_version: string;
}

// Mirrors corp/core/schemas/dossier.py DossierResponse, which is what
// GET /creators/{id}/dossier.json returns.
export interface ProblemCluster {
  id: string;
  label: string;
  description: string | null;
  frequency: number;
  recency_score: number;
  evidence_strength: number;
  creator_count: number;
  model_version: string | null;
}

export interface DossierOpportunity {
  cluster: ProblemCluster;
  score: OpportunityScore;
  signal: CommercialSignal | null;
  observations: ProblemObservation[];
  competitors: Competitor[];
}

export interface DossierJson {
  creator: {
    id: string;
    name: string;
    niche: string | null;
    status: CreatorStatus;
  };
  platform_accounts: Array<{
    platform: string;
    handle: string;
    subscriber_count: number | null;
  }>;
  creator_score: {
    id: string;
    component_scores: Record<string, number>;
    aggregate_score: number;
    confidence_band: string;
  } | null;
  score_band: string;
  weights: Record<string, number>;
  opportunities: DossierOpportunity[];
  signals: Array<{ cluster_label: string; signal: CommercialSignal }>;
  data_coverage: {
    source_count: number;
    evidence_count: number;
    cluster_count: number;
    observation_count: number;
    competitor_count: number;
  };
  generated_at: string;
}

// R12d — the last re-research outcome for a watched dossier (design §3.5).
// A resurfaced (or Research More) version is WATCHING again once the
// reviewer parks it, so all three outcomes can appear.
export interface LastRescan {
  outcome: "unchanged" | "resurfaced" | "failed";
  trigger: "watch" | "research_more" | null;
  at: string;
  reason: string | null;
  score_delta: number | null;
  new_evidence_count: number | null;
  error: string | null;
  run_id: string | null;
}

// Re-scan schedule visibility — watching dossiers with niche recheck info.
export interface WatchingDossier {
  id: string;
  creator_id: string;
  creator_name: string;
  niche_id: string;
  niche_name: string;
  status: string;
  generated_at: string;
  next_recheck_at: string | null;
  last_rescan: LastRescan | null;
}

// R12a — written by WatchRescanner on every dossier version it produces
// (Watch re-scan or Research More); explains why this version exists.
export interface DossierRescanBlock {
  trigger: "watch" | "research_more";
  previous_dossier_id: string;
  resurfaced: boolean;
  reason: string;
  score_delta: number | null;
  new_evidence_count: number;
  run_id: string;
  at: string;
}

// CORP1 Stage 5, T8 — the dossier-level four-state decision gate.
// Distinct from Decision above (Gate A, creator-status-scoped).
export type DossierDecisionType = "reject" | "research_more" | "watch" | "approve";

export interface DossierDecisionInput {
  decision: DossierDecisionType;
  rationale?: string | null;
  decided_by?: string | null;
}

export interface DossierDecisionResult {
  id: string;
  dossier_id: string;
  creator_id: string;
  decision: DossierDecisionType;
  gate: string;
  rationale: string | null;
  decided_at: string;
  dossier_status: string;
  job_id: string | null;
}

// CORP1 Stage 5, T6 — the real, persisted Dossier row (not the
// live-computed DossierJson above).
export interface PersistedDossier {
  id: string;
  creator_id: string;
  niche_id: string;
  status: string;
  generated_at: string;
  content: {
    product_ideas: Array<{
      id: string;
      title: string;
      description: string;
      idea_type: string;
      complexity: string;
      price_min: number | null;
      price_max: number | null;
      fit_rationale: string;
      evidence_terms: string[];
      comparable_products?: Array<{ name: string; url: string | null; strength: string }>;
    }>;
    opportunities?: Array<{
      cluster_label: string;
      cluster_description: string | null;
      aggregate_score: number;
      confidence_band: string;
      signal_level: string | null;
      observation_count: number;
      sample_evidence: string[];
      frequency: number;
      competitor_count: number;
    }>;
    // Spec "Audience Analysis" section (R7): what the audience says, in
    // its own words, grouped by problem cluster.
    audience_analysis?: {
      top_questions: Array<{
        cluster_label: string;
        questions: Array<{ text: string; sentiment: string | null; urgency: string | null }>;
      }>;
      recurring_themes: Array<{
        label: string;
        description: string | null;
        frequency: number;
        observation_count: number;
        evidence_strength: number;
        recency_score: number;
      }>;
      language_patterns: Array<{ pattern: string; count: number }>;
      engagement_quality: {
        total_audience_observations: number;
        sentiment_distribution: Record<string, number>;
        urgency_distribution: Record<string, number>;
      };
    };
    // Spec "Demand Validation" section (R7): external evidence counted by
    // capability type and by source platform.
    demand_validation?: {
      evidence_by_type: Record<string, number>;
      evidence_by_platform: Record<string, number>;
      signals: Record<string, number>;
      platform_highlights: Record<string, number>;
    };
    niche_path: Array<{ id: string; canonical_name: string; depth: number }>;
    recommendation: {
      suggested_action: string;
      confidence: string;
      rationale: string;
      risks: string[];
      next_steps: string[];
    };
    rescan?: DossierRescanBlock;
    [key: string]: unknown;
  };
}


