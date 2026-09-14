import { useState } from "react";
import { useParams } from "react-router-dom";
import { useCreator, useJob, useStartResearch } from "../api/hooks";
import { Button, Card, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

export function CreatorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: creator, isLoading, error } = useCreator(id);
  const startResearch = useStartResearch();
  const [activeJobId, setActiveJobId] = useState<string | undefined>();
  const { data: job } = useJob(activeJobId, { pollUntilDone: true });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner error={error} />;
  if (!creator) return null;

  return (
    <div className="space-y-6">
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
              onSuccess: (job) => setActiveJobId(job.id),
            })
          }
          disabled={startResearch.isPending || (job && job.status === "running")}
        >
          {startResearch.isPending ? "Starting…" : "Start Research"}
        </Button>
      </div>

      {startResearch.error && <ErrorBanner error={startResearch.error} />}

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
    </div>
  );
}
