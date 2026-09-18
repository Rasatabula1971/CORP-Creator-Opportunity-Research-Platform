import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  useClusters,
  useClusterObservations,
  useCreator,
  useDecisions,
  useDossier,
  useGeneratePersistedDossier,
  useJob,
  usePersistedDossier,
  useRecordDecision,
  useStartResearch,
} from "../api/hooks";
import { Button, Card, ErrorBanner, Spinner, StatusBadge } from "../components/ui";
import { ApiError } from "../api/client";
import type { ClusterDetail, Competitor } from "../api/types";

export function CreatorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: creator, isLoading, error } = useCreator(id);
  const { data: clusters } = useClusters(id);
  const { data: dossier } = useDossier(id);
  const { data: decisions } = useDecisions(id);
  const startResearch = useStartResearch();
  const [activeJobId, setActiveJobId] = useState<string | undefined>();
  const { data: job } = useJob(activeJobId, { pollUntilDone: true });
  const [expandedCluster, setExpandedCluster] = useState<string | null>(null);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;
  if (!creator) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">{creator.name}</h1>
            <StatusBadge status={creator.status} />
          </div>
          <p className="mt-1 text-sm text-neutral-500">
            {creator.niche ?? "No niche set"} · {creator.discovery_source ?? "manual"}
          </p>
        </div>
        <Button
          onClick={() =>
            startResearch.mutate(creator.id, {
              onSuccess: (j) => setActiveJobId(j.id),
            })
          }
          disabled={startResearch.isPending || job?.status === "queued" || job?.status === "running"}
        >
          {startResearch.isPending ? "Starting…" : "Start Research"}
        </Button>
      </div>

      {startResearch.error && <ErrorBanner error={startResearch.error} />}

      {/* Active job */}
      {job && (
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Research job {job.id.slice(0, 8)}</p>
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

      {/* Data Coverage + Score */}
      {dossier && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <StatTile label="Score Band" value={dossier.score_band} />
          <StatTile
            label="Sources"
            value={String(dossier.data_coverage.source_count)}
          />
          <StatTile
            label="Evidence"
            value={String(dossier.data_coverage.evidence_count)}
          />
          <StatTile
            label="Clusters"
            value={String(dossier.data_coverage.cluster_count)}
          />
          <StatTile
            label="Competitors"
            value={String(dossier.data_coverage.competitor_count ?? 0)}
          />
        </div>
      )}

      {/* Decision Actions */}
      {id && creator.status !== "approved" && creator.status !== "rejected" && (
        <DecisionPanel creatorId={id} />
      )}

      {/* Persisted Dossier (CORP1 Stage 5, T6) */}
      {id && <PersistedDossierPanel creatorId={id} />}

      {/* Opportunities / Clusters */}
      <Card>
        <h2 className="mb-3 text-sm font-semibold">
          Opportunities{clusters ? ` (${clusters.length})` : ""}
        </h2>
        {!clusters || clusters.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No clusters found. Run research to discover opportunities.
          </p>
        ) : (
          <div className="space-y-3">
            {clusters.map((c) => (
              <ClusterCard
                key={c.id}
                cluster={c}
                competitors={
                  dossier?.opportunities.find(
                    (o) => o.cluster.id === c.id,
                  )?.competitors ?? []
                }
                expanded={expandedCluster === c.id}
                onToggle={() =>
                  setExpandedCluster(expandedCluster === c.id ? null : c.id)
                }
              />
            ))}
          </div>
        )}
      </Card>

      {/* Decision History */}
      {decisions && decisions.length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold">Decision History</h2>
          <div className="space-y-2">
            {decisions.map((d) => (
              <div
                key={d.id}
                className="flex items-center justify-between rounded border border-neutral-100 px-3 py-2 text-sm dark:border-neutral-800"
              >
                <div className="flex items-center gap-3">
                  <StatusBadge status={d.decision} />
                  <span className="text-neutral-500">{d.gate}</span>
                </div>
                <div className="text-right">
                  {d.rationale && (
                    <p className="text-xs text-neutral-500">{d.rationale}</p>
                  )}
                  <p className="text-xs text-neutral-400">
                    {new Date(d.decided_at).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Platform Accounts */}
      <Card>
        <h2 className="mb-3 text-sm font-semibold">Platform Accounts</h2>
        {creator.platform_accounts.length === 0 ? (
          <p className="text-sm text-neutral-500">No accounts linked.</p>
        ) : (
          <ul className="space-y-2">
            {creator.platform_accounts.map((a) => (
              <li key={a.id} className="flex items-center justify-between text-sm">
                <span className="font-medium capitalize">{a.platform}</span>
                <span className="text-neutral-500">{a.handle}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Score Weights */}
      {dossier && Object.keys(dossier.weights).length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-semibold">Score Weights</h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(dossier.weights).map(([key, val]) => (
              <div key={key} className="text-sm">
                <span className="text-neutral-500">{key.replace(/_/g, " ")}</span>
                <span className="ml-2 font-medium">{val.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs font-medium text-neutral-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

// Competitor URLs come from the LLM/scraping pipeline unvalidated; only let
// http(s) through so a javascript:/data: value can't become a clickable href.
function safeUrl(u: string | null | undefined): string | null {
  return u && /^https?:\/\//i.test(u) ? u : null;
}

function ClusterCard({
  cluster,
  competitors,
  expanded,
  onToggle,
}: {
  cluster: ClusterDetail;
  competitors: Competitor[];
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {cluster.label ?? `Cluster ${cluster.id.slice(0, 8)}`}
          </p>
          {cluster.description && (
            <p className="mt-0.5 truncate text-xs text-neutral-500">
              {cluster.description}
            </p>
          )}
        </div>
        <div className="ml-4 flex items-center gap-3">
          {cluster.score && (
            <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs font-semibold dark:bg-neutral-800">
              {cluster.score.aggregate_score.toFixed(2)}
            </span>
          )}
          {cluster.signal && (
            <StatusBadge status={cluster.signal.signal_level} />
          )}
          <span className="text-xs text-neutral-400">
            {cluster.member_count} obs
          </span>
          <span className="text-neutral-400">{expanded ? "−" : "+"}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-neutral-100 px-4 py-3 dark:border-neutral-800">
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <div>
              <span className="text-neutral-500">Frequency</span>
              <p className="font-medium">{cluster.frequency ?? "—"}</p>
            </div>
            <div>
              <span className="text-neutral-500">Recency</span>
              <p className="font-medium">
                {cluster.recency_score?.toFixed(2) ?? "—"}
              </p>
            </div>
            <div>
              <span className="text-neutral-500">Evidence Strength</span>
              <p className="font-medium">
                {cluster.evidence_strength?.toFixed(2) ?? "—"}
              </p>
            </div>
            {cluster.score?.confidence_band && (
              <div>
                <span className="text-neutral-500">Confidence</span>
                <p className="font-medium">{cluster.score.confidence_band}</p>
              </div>
            )}
          </div>

          {cluster.score && Object.keys(cluster.score.component_scores).length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-medium text-neutral-500">
                Component Scores
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(cluster.score.component_scores).map(
                  ([key, val]) => (
                    <span
                      key={key}
                      className="rounded bg-neutral-100 px-2 py-0.5 text-xs dark:bg-neutral-800"
                    >
                      {key.replace(/_/g, " ")}: {val.toFixed(2)}
                    </span>
                  ),
                )}
              </div>
            </div>
          )}

          {cluster.signal?.rationale && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-medium text-neutral-500">
                Signal Rationale
              </p>
              <p className="text-xs text-neutral-600 dark:text-neutral-400">
                {cluster.signal.rationale}
              </p>
            </div>
          )}

          {competitors.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs font-medium text-neutral-500">
                Competitors ({competitors.length})
              </p>
              <ul className="space-y-1">
                {competitors.map((c) => (
                  <li
                    key={c.id}
                    className="flex items-start justify-between gap-2 rounded bg-neutral-50 px-2 py-1 text-xs dark:bg-neutral-800/50"
                  >
                    <div className="min-w-0 flex-1">
                      {safeUrl(c.url) ? (
                        <a
                          href={safeUrl(c.url)!}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="font-medium underline decoration-neutral-400 hover:decoration-neutral-700"
                        >
                          {c.name}
                        </a>
                      ) : (
                        <span className="font-medium">{c.name}</span>
                      )}
                      {c.gap_notes && (
                        <p className="mt-0.5 text-neutral-500">{c.gap_notes}</p>
                      )}
                    </div>
                    <div className="flex flex-none gap-1">
                      <CompetitorBadge kind="type" value={c.competitor_type} />
                      <CompetitorBadge kind="strength" value={c.strength} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <ObservationsPreview clusterId={cluster.id} />
        </div>
      )}
    </div>
  );
}

function CompetitorBadge({
  kind,
  value,
}: {
  kind: "type" | "strength";
  value: string;
}) {
  const palette: Record<string, string> =
    kind === "strength"
      ? {
          weak: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
          moderate: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
          strong: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
        }
      : {
          direct: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
          substitute:
            "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
          diy_workaround:
            "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
        };
  const cls =
    palette[value] ??
    "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
      {value.replace(/_/g, " ")}
    </span>
  );
}

function ObservationsPreview({ clusterId }: { clusterId: string }) {
  const { data } = useClusterObservations(clusterId);
  if (!data || data.items.length === 0) return null;

  return (
    <div className="mt-3">
      <p className="mb-1 text-xs font-medium text-neutral-500">
        Observations ({data.totalCount})
      </p>
      <ul className="space-y-1">
        {data.items.slice(0, 5).map((obs) => (
          <li
            key={obs.id}
            className="rounded bg-neutral-50 px-2 py-1 text-xs dark:bg-neutral-800/50"
          >
            <div>{obs.text}</div>
            <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
              {obs.category && (
                <span className="text-neutral-400">[{obs.category}]</span>
              )}
              {obs.urgency && obs.urgency !== "low" && (
                <UrgencyPill value={obs.urgency} />
              )}
              {obs.sentiment && obs.sentiment !== "neutral" && (
                <SentimentPill value={obs.sentiment} />
              )}
              {obs.source_side === "creator" && (
                <span className="rounded bg-sky-100 px-1 py-0.5 text-sky-700 dark:bg-sky-900/40 dark:text-sky-200">
                  creator
                </span>
              )}
              {obs.is_inferred && (
                <span className="rounded bg-violet-100 px-1 py-0.5 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200">
                  inferred
                </span>
              )}
            </div>
          </li>
        ))}
        {data.totalCount > 5 && (
          <li className="text-xs text-neutral-400">
            +{data.totalCount - 5} more
          </li>
        )}
      </ul>
    </div>
  );
}

function UrgencyPill({ value }: { value: "low" | "medium" | "high" }) {
  const cls =
    value === "high"
      ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-200"
      : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-200";
  return <span className={`rounded px-1 py-0.5 font-medium ${cls}`}>{value}</span>;
}

function SentimentPill({
  value,
}: {
  value: "positive" | "neutral" | "negative";
}) {
  const cls =
    value === "positive"
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200"
      : "bg-neutral-200 text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200";
  return <span className={`rounded px-1 py-0.5 font-medium ${cls}`}>{value}</span>;
}

function PersistedDossierPanel({ creatorId }: { creatorId: string }) {
  const { data: persisted, isLoading, error } = usePersistedDossier(creatorId);
  const generate = useGeneratePersistedDossier();

  // A 404 genuinely means "no dossier yet" -- anything else (500, network
  // failure, auth) is a real error that must not be silently displayed as
  // the same empty state.
  const isNotFound = error instanceof ApiError && error.status === 404;
  const isRealError = !!error && !isNotFound;

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Persisted Dossier</h2>
        <Button
          variant="secondary"
          onClick={() => generate.mutate(creatorId)}
          disabled={generate.isPending}
        >
          {generate.isPending ? "Generating…" : persisted ? "Regenerate" : "Generate Dossier"}
        </Button>
      </div>

      {generate.error && <ErrorBanner error={generate.error} />}
      {isRealError && <ErrorBanner error={error} />}

      {isLoading && !persisted ? null : isRealError ? null : !persisted ? (
        <p className="mt-2 text-sm text-neutral-500">
          No persisted dossier yet. Generate one once this creator has a scored opportunity.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-3 text-xs text-neutral-500">
            <StatusBadge status={persisted.status} />
            <span>Generated {new Date(persisted.generated_at).toLocaleString()}</span>
          </div>

          {persisted.content.niche_path?.length > 0 && (
            <p className="text-xs text-neutral-500">
              {persisted.content.niche_path.map((n) => n.canonical_name).join(" → ")}
            </p>
          )}

          {persisted.content.recommendation && (
            <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <div className="flex items-center gap-2">
                <StatusBadge status={persisted.content.recommendation.suggested_action} />
                <span className="text-xs text-neutral-500">
                  {persisted.content.recommendation.confidence} confidence
                </span>
              </div>
              <p className="mt-2 text-sm">{persisted.content.recommendation.rationale}</p>
              {persisted.content.recommendation.risks.length > 0 && (
                <div className="mt-2">
                  <p className="text-xs font-medium text-neutral-500">Risks</p>
                  <ul className="mt-1 list-inside list-disc text-xs text-neutral-600 dark:text-neutral-400">
                    {persisted.content.recommendation.risks.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {persisted.content.recommendation.next_steps.length > 0 && (
                <div className="mt-2">
                  <p className="text-xs font-medium text-neutral-500">Next steps</p>
                  <ul className="mt-1 list-inside list-disc text-xs text-neutral-600 dark:text-neutral-400">
                    {persisted.content.recommendation.next_steps.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {persisted.content.product_ideas?.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-neutral-500">
                Product Ideas ({persisted.content.product_ideas.length})
              </p>
              <div className="space-y-2">
                {persisted.content.product_ideas.map((idea) => (
                  <div
                    key={idea.id}
                    className="rounded bg-neutral-50 px-3 py-2 text-xs dark:bg-neutral-800/50"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{idea.title}</span>
                      <span className="text-neutral-400">
                        {idea.idea_type.replace(/_/g, " ")} · {idea.complexity}
                        {idea.price_min != null && idea.price_max != null
                          ? ` · $${idea.price_min}–$${idea.price_max}`
                          : ""}
                      </span>
                    </div>
                    <p className="mt-1 text-neutral-500">{idea.fit_rationale}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function DecisionPanel({ creatorId }: { creatorId: string }) {
  const recordDecision = useRecordDecision(creatorId);
  const [rationale, setRationale] = useState("");
  const [showForm, setShowForm] = useState(false);

  function submit(decision: "approve" | "reject" | "watch") {
    recordDecision.mutate(
      { decision, rationale: rationale || null },
      {
        onSuccess: () => {
          setRationale("");
          setShowForm(false);
        },
      },
    );
  }

  if (!showForm) {
    return (
      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Gate A Decision</h2>
          <Button variant="secondary" onClick={() => setShowForm(true)}>
            Record Decision
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold">Gate A Decision</h2>
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-500">
            Rationale (optional)
          </label>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
        </div>

        {recordDecision.error && <ErrorBanner error={recordDecision.error} />}

        <div className="flex gap-2">
          <Button
            onClick={() => submit("approve")}
            disabled={recordDecision.isPending}
          >
            Approve
          </Button>
          <Button
            variant="secondary"
            onClick={() => submit("watch")}
            disabled={recordDecision.isPending}
          >
            Watch
          </Button>
          <Button
            variant="danger"
            onClick={() => submit("reject")}
            disabled={recordDecision.isPending}
          >
            Reject
          </Button>
          <Button
            variant="secondary"
            onClick={() => setShowForm(false)}
            disabled={recordDecision.isPending}
          >
            Cancel
          </Button>
        </div>
      </div>
    </Card>
  );
}
