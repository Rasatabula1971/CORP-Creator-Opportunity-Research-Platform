import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./client";
import type {
  Campaign,
  CampaignCreateInput,
  CampaignNiche,
  ClusterDetail,
  Creator,
  CreatorCreateInput,
  CreatorDetail,
  Decision,
  DossierDecisionInput,
  DossierDecisionResult,
  DossierJson,
  Job,
  MicroNiche,
  MicroNicheDecision,
  MicroNicheStatus,
  MicroNicheSuggestStats,
  PersistedDossier,
  ProblemObservation,
  ResearchRun,
  WatchingDossier,
} from "./types";

// Backend list endpoints default to limit=50 and cap at 200; ask for the cap
// so lists don't silently truncate.
const LIST_LIMIT = 200;

export function useCreators() {
  return useQuery({
    queryKey: ["creators"],
    queryFn: () => api.getWithCount<Creator>(`/creators?limit=${LIST_LIMIT}`),
  });
}

export function useArchivedCreators(enabled: boolean) {
  return useQuery({
    queryKey: ["creators", "archived"],
    queryFn: () =>
      api.getWithCount<Creator>(`/creators?include_archived=true&limit=${LIST_LIMIT}`).then((r) => ({
        ...r,
        items: r.items.filter((c) => c.archived_at != null),
      })),
    enabled,
  });
}

export function useCreator(id: string | undefined) {
  return useQuery({
    queryKey: ["creators", id],
    queryFn: () => api.get<CreatorDetail>(`/creators/${id}`),
    enabled: !!id,
  });
}

// Reversible hide-from-the-list for test/demo/mistaken entries; never
// touches evidence or any other row (append-only Provenance Invariant, R3).
export function useArchiveCreator(creatorId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (archive: boolean) =>
      api.post<CreatorDetail>(`/creators/${creatorId}/${archive ? "archive" : "unarchive"}`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["creators", creatorId] });
      qc.invalidateQueries({ queryKey: ["creators"], exact: true });
    },
  });
}

export function useCreateCreator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreatorCreateInput) => api.post<CreatorDetail>("/creators", input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["creators"] }),
  });
}

export function useClusters(creatorId: string | undefined) {
  return useQuery({
    queryKey: ["creators", creatorId, "clusters"],
    queryFn: () => api.get<ClusterDetail[]>(`/creators/${creatorId}/clusters`),
    enabled: !!creatorId,
  });
}

export function useClusterObservations(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["clusters", clusterId, "observations"],
    queryFn: () =>
      api.getWithCount<ProblemObservation>(`/clusters/${clusterId}/observations`),
    enabled: !!clusterId,
  });
}

export function useDossier(creatorId: string | undefined) {
  return useQuery({
    queryKey: ["creators", creatorId, "dossier"],
    queryFn: () => api.get<DossierJson>(`/creators/${creatorId}/dossier.json`),
    enabled: !!creatorId,
  });
}

// CORP1 Stage 5, T6 — the real, persisted Dossier (not the live-computed
// useDossier view above). 404 just means none has been generated yet.
export function usePersistedDossier(creatorId: string | undefined) {
  return useQuery({
    queryKey: ["creators", creatorId, "dossier", "persisted"],
    queryFn: () => api.get<PersistedDossier>(`/creators/${creatorId}/dossier/persisted`),
    enabled: !!creatorId,
    retry: false,
  });
}

export function useGeneratePersistedDossier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (creatorId: string) =>
      api.post<PersistedDossier>(`/creators/${creatorId}/dossier/generate`),
    onSuccess: (_data, creatorId) => {
      qc.invalidateQueries({ queryKey: ["creators", creatorId, "dossier", "persisted"] });
    },
  });
}

export function useDecisions(creatorId: string | undefined) {
  return useQuery({
    queryKey: ["creators", creatorId, "decisions"],
    queryFn: () => api.get<Decision[]>(`/creators/${creatorId}/decisions`),
    enabled: !!creatorId,
  });
}

export function useResearchRuns() {
  return useQuery({
    queryKey: ["research-runs"],
    queryFn: () => api.get<ResearchRun[]>(`/research-runs?limit=${LIST_LIMIT}`),
  });
}

export function useJobs(creatorId?: string) {
  return useQuery({
    queryKey: ["jobs", creatorId ?? "all"],
    queryFn: () =>
      api.get<Job[]>(
        `/jobs?limit=${LIST_LIMIT}${creatorId ? `&creator_id=${creatorId}` : ""}`,
      ),
    refetchInterval: 4000,
  });
}

export function useJob(jobId: string | undefined, opts?: { pollUntilDone?: boolean }) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["jobs", "detail", jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (!opts?.pollUntilDone) return false;
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 2000;
    },
  });

  // A finished job has written clusters, scores, niches and creators that
  // nothing else refetches (no refetchInterval on those queries, and
  // staleTime keeps the cache warm). Invalidate once per job when it settles
  // so the page shows the results without a navigate-away-and-back.
  const status = query.data?.status;
  const settledFor = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!jobId || !opts?.pollUntilDone) return;
    if (status !== "completed" && status !== "failed") return;
    if (settledFor.current === jobId) return;
    settledFor.current = jobId;
    qc.invalidateQueries({ queryKey: ["creators"] });
    qc.invalidateQueries({ queryKey: ["campaigns"] });
    qc.invalidateQueries({ queryKey: ["clusters"] });
    qc.invalidateQueries({ queryKey: ["research-runs"] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
  }, [jobId, status, opts?.pollUntilDone, qc]);

  return query;
}

export function useStartResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (creatorId: string) =>
      api.post<Job>(`/creators/${creatorId}/research`, {}),
    onSuccess: (_data, creatorId) =>
      qc.invalidateQueries({ queryKey: ["jobs", creatorId] }),
  });
}

// ── Campaigns ────────────────────────────────────────────────────────

export function useCampaigns() {
  return useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.get<Campaign[]>(`/campaigns?limit=${LIST_LIMIT}`),
  });
}

export function useCampaign(id: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", id],
    queryFn: () => api.get<Campaign>(`/campaigns/${id}`),
    enabled: !!id,
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CampaignCreateInput) =>
      api.post<Campaign>("/campaigns", input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useCampaignNiches(campaignId: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", campaignId, "niches"],
    queryFn: () =>
      api.getWithCount<CampaignNiche>(`/campaigns/${campaignId}/niches?limit=${LIST_LIMIT}`),
    enabled: !!campaignId,
  });
}

export function useCampaignCreators(campaignId: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", campaignId, "creators"],
    queryFn: () =>
      api.getWithCount<Creator>(`/campaigns/${campaignId}/creators?limit=${LIST_LIMIT}`),
    enabled: !!campaignId,
  });
}

export function useStartCampaignPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      campaignId,
      stage,
      source,
      query,
    }: {
      campaignId: string;
      stage: string;
      source?: string;
      query?: string;
    }) =>
      api.post<Job>(`/campaigns/${campaignId}/${stage}`, { source, query }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["campaigns", vars.campaignId] });
    },
  });
}

export function useRecordDecision(creatorId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      opportunity_score_id?: string | null;
      decision: "approve" | "reject" | "watch";
      rationale?: string | null;
      decided_by?: string | null;
    }) =>
      api.post<Decision>(`/creators/${creatorId}/decisions`, input),
    // The gate also transitions creator.status; the prefix key refreshes the
    // detail (header badge, DecisionPanel gate) and the decisions list together.
    onSuccess: () => qc.invalidateQueries({ queryKey: ["creators", creatorId] }),
  });
}

// CORP1 Stage 5, T8 — the dossier-level four-state decision gate, distinct
// from useRecordDecision above (Gate A, creator-status-scoped, unchanged).
export function useRecordDossierDecision(creatorId: string, dossierId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: DossierDecisionInput) =>
      api.post<DossierDecisionResult>(`/dossiers/${dossierId}/decision`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["creators", creatorId, "dossier", "persisted"] });
      // R12b: the dossier gate now moves Creator.status too, so the creator
      // detail (badge, Gate A panel visibility) and the creator list must refresh.
      qc.invalidateQueries({ queryKey: ["creators", creatorId] });
      qc.invalidateQueries({ queryKey: ["creators"], exact: true });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ── Watching dossiers (re-scan schedule) ────────────────────────────

export function useWatchingDossiers() {
  return useQuery({
    queryKey: ["dossiers", "watching"],
    queryFn: () => api.get<WatchingDossier[]>(`/dossiers/watching?limit=${LIST_LIMIT}`),
  });
}

// ── Micro-niches (creator-first discovery, approval first) ──────────

export function useMicroNiches(status: MicroNicheStatus) {
  return useQuery({
    queryKey: ["micro-niches", status],
    queryFn: () =>
      api.getWithCount<MicroNiche>(`/micro-niches?status=${status}&limit=${LIST_LIMIT}`),
  });
}

export function useSuggestMicroNiches() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<MicroNicheSuggestStats>("/micro-niches/suggest", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["micro-niches"] }),
  });
}

export function useApproveMicroNiche() {
  const qc = useQueryClient();
  return useMutation({
    // topic is only sent when the reviewer reworded the label.
    mutationFn: ({ id, topic }: { id: string; topic?: string }) =>
      api.post<MicroNicheDecision>(`/micro-niches/${id}/approve`, topic ? { topic } : {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["micro-niches"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useRejectMicroNiche() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<MicroNicheDecision>(`/micro-niches/${id}/reject`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["micro-niches"] }),
  });
}
