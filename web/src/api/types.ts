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
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
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

export interface DossierJson {
  creator: CreatorDetail;
  creator_score: Record<string, unknown> | null;
  score_band: string;
  weights: Record<string, number>;
  opportunities: Array<{
    cluster: ClusterDetail;
    score: OpportunityScore;
    signal: SignalSummary | null;
    observations: ProblemObservation[];
  }>;
  data_coverage: {
    source_count: number;
    evidence_count: number;
    cluster_count: number;
    observation_count: number;
  };
  generated_at: string;
}

export interface Paged<T> {
  items: T[];
  totalCount: number;
}
