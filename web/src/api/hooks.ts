import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  DossierJson,
  Job,
  ProblemObservation,
  ResearchRun,
} from "./types";

export function useCreators() {
  return useQuery({
    queryKey: ["creators"],
    queryFn: () => api.getWithCount<Creator>("/creators"),
  });
}

export function useCreator(id: string | undefined) {
  return useQuery({
    queryKey: ["creators", id],
    queryFn: () => api.get<CreatorDetail>(`/creators/${id}`),
    enabled: !!id,
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
    queryFn: () => api.get<ResearchRun[]>("/research-runs"),
  });
}

export function useJobs(creatorId?: string) {
  return useQuery({
    queryKey: ["jobs", creatorId ?? "all"],
    queryFn: () =>
      api.get<Job[]>(`/jobs${creatorId ? `?creator_id=${creatorId}` : ""}`),
    refetchInterval: 4000,
  });
}

export function useJob(jobId: string | undefined, opts?: { pollUntilDone?: boolean }) {
  return useQuery({
    queryKey: ["jobs", "detail", jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (!opts?.pollUntilDone) return false;
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 2000;
    },
  });
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

export function useStartPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      creatorId,
      pipeline,
      platform,
      identifier,
    }: {
      creatorId: string;
      pipeline: string;
      platform?: string;
      identifier?: string;
    }) =>
      api.post<Job>(`/creators/${creatorId}/runs`, { pipeline, platform, identifier }),
    onSuccess: (_data, vars) =>
      qc.invalidateQueries({ queryKey: ["jobs", vars.creatorId] }),
  });
}

// ── Campaigns ────────────────────────────────────────────────────────

export function useCampaigns() {
  return useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.get<Campaign[]>("/campaigns"),
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
    queryFn: () => api.get<CampaignNiche[]>(`/campaigns/${campaignId}/niches`),
    enabled: !!campaignId,
  });
}

export function useCampaignCreators(campaignId: string | undefined) {
  return useQuery({
    queryKey: ["campaigns", campaignId, "creators"],
    queryFn: () => api.get<Creator[]>(`/campaigns/${campaignId}/creators`),
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
      gate?: string;
    }) =>
      api.post<Decision>(`/creators/${creatorId}/decisions`, {
        creator_id: creatorId,
        gate: "gate_a",
        ...input,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["creators", creatorId, "decisions"] }),
  });
}
