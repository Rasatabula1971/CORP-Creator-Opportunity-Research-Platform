export type CreatorStatus = string;

export interface PlatformAccount {
  id: string;
  creator_id: string;
  platform: string;
  handle: string;
  external_id: string | null;
  verified: boolean;
}

export interface Creator {
  id: string;
  name: string;
  niche: string | null;
  discovery_source: string | null;
  status: CreatorStatus;
  notes: string | null;
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

export interface ScoreDiagnostics {
  [key: string]: unknown;
}

export interface OpportunityScore {
  id: string;
  creator_id: string;
  problem_cluster_id: string;
  component_scores: Record<string, number>;
  aggregate_score: number;
  confidence_band: string | null;
  diagnostics: ScoreDiagnostics | null;
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
  opportunity_id: string | null;
  decision: string;
  rationale: string | null;
  decided_at: string;
  gate: string;
}

export interface ResearchRun {
  id: string;
  creator_id: string | null;
  scope: string;
  status: string;
  started_at: string;
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

export interface Paged<T> {
  items: T[];
  totalCount: number;
}
