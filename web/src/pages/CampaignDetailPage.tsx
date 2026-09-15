import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  useCampaign,
  useCampaignCreators,
  useCampaignNiches,
  useJob,
  useStartCampaignPipeline,
} from "../api/hooks";
import { Button, Card, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

const PIPELINE_STAGES = [
  { key: "discover", label: "Discover Niches", needsInput: true },
  { key: "candidates", label: "Generate Candidates" },
  { key: "canonicalize", label: "Canonicalize" },
  { key: "verify", label: "Verify" },
  { key: "estimate-ecosystem", label: "Estimate Ecosystem" },
  { key: "qualify", label: "Qualify" },
  { key: "select", label: "Select" },
  { key: "onboard", label: "Onboard Creators" },
  { key: "research-campaign", label: "Research Campaign" },
] as const;

export function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: campaign, isLoading, error } = useCampaign(id);
  const { data: niches } = useCampaignNiches(id);
  const { data: creators } = useCampaignCreators(id);
  const startPipeline = useStartCampaignPipeline();
  const [activeJobId, setActiveJobId] = useState<string | undefined>();
  const { data: job } = useJob(activeJobId, { pollUntilDone: true });
  const [discoverSource, setDiscoverSource] = useState("youtube");
  const [discoverQuery, setDiscoverQuery] = useState("");

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;
  if (!campaign) return null;

  function runStage(stage: string) {
    if (!id) return;
    const params: { campaignId: string; stage: string; source?: string; query?: string } = {
      campaignId: id,
      stage,
    };
    if (stage === "discover") {
      params.source = discoverSource;
      params.query = discoverQuery;
    }
    startPipeline.mutate(params, {
      onSuccess: (j) => setActiveJobId(j.id),
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">{campaign.name}</h1>
            <StatusBadge status={campaign.status} />
          </div>
          <p className="mt-1 text-sm text-neutral-500">
            {campaign.target_niche_count} niches target ·{" "}
            {campaign.initial_creators_per_niche} creators/niche ·{" "}
            {campaign.creator_min_followers.toLocaleString()}&ndash;
            {campaign.creator_max_followers.toLocaleString()} followers
          </p>
        </div>
      </div>

      {startPipeline.error && <ErrorBanner error={startPipeline.error} />}

      {job && (
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Job {job.id.slice(0, 8)}</p>
              <p className="text-xs text-neutral-500">{job.kind}</p>
            </div>
            <StatusBadge status={job.status} />
          </div>
          {job.error && <p className="mt-2 text-xs text-red-600">{job.error}</p>}
          {job.status === "completed" && job.result && (
            <pre className="mt-2 overflow-x-auto rounded bg-neutral-100 p-2 text-xs dark:bg-neutral-800">
              {JSON.stringify(job.result, null, 2)}
            </pre>
          )}
        </Card>
      )}

      <Card>
        <h2 className="mb-3 text-sm font-semibold">Pipeline</h2>
        <div className="space-y-3">
          {PIPELINE_STAGES.map((stage) => (
            <div key={stage.key} className="flex items-center gap-3">
              {stage.needsInput && (
                <div className="flex flex-1 gap-2">
                  <select
                    value={discoverSource}
                    onChange={(e) => setDiscoverSource(e.target.value)}
                    className="rounded-md border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700 dark:bg-neutral-950"
                  >
                    <option value="youtube">YouTube</option>
                    <option value="reddit">Reddit</option>
                    <option value="tiktok">TikTok</option>
                  </select>
                  <input
                    placeholder="Search query..."
                    value={discoverQuery}
                    onChange={(e) => setDiscoverQuery(e.target.value)}
                    className="flex-1 rounded-md border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700 dark:bg-neutral-950"
                  />
                </div>
              )}
              <Button
                variant="secondary"
                onClick={() => runStage(stage.key)}
                disabled={
                  startPipeline.isPending ||
                  (job !== undefined && job.status === "running") ||
                  (stage.key === "discover" && !discoverQuery.trim())
                }
              >
                {stage.label}
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-semibold">
          Niches{niches ? ` (${niches.length})` : ""}
        </h2>
        {!niches || niches.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No niches discovered yet. Run the Discover stage to find niches.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
                <tr>
                  <th className="px-3 py-2 font-medium">Niche</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Score</th>
                  <th className="px-3 py-2 font-medium">Creators</th>
                  <th className="px-3 py-2 font-medium">Selected</th>
                </tr>
              </thead>
              <tbody>
                {niches.map((cn) => (
                  <tr
                    key={cn.id}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                  >
                    <td className="px-3 py-2 font-medium">
                      {cn.niche?.canonical_name ?? cn.niche_id.slice(0, 8)}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={cn.status} />
                    </td>
                    <td className="px-3 py-2 text-neutral-500">
                      {cn.qualification_score != null
                        ? cn.qualification_score.toFixed(2)
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-neutral-500">
                      {cn.creator_count_observed}
                    </td>
                    <td className="px-3 py-2">
                      {cn.selected ? (
                        <span className="text-green-600">Yes</span>
                      ) : (
                        <span className="text-neutral-400">No</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-semibold">
          Onboarded Creators{creators ? ` (${creators.length})` : ""}
        </h2>
        {!creators || creators.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No creators onboarded yet. Run the Onboard stage after niche selection.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
                <tr>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {creators.map((cr) => (
                  <tr
                    key={cr.id}
                    className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                  >
                    <td className="px-3 py-2 font-medium">{cr.name}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={cr.status} />
                    </td>
                    <td className="px-3 py-2 text-neutral-500">
                      {cr.discovery_source ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
