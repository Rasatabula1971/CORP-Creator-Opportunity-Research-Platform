import { useWatchingDossiers } from "../api/hooks";
import type { LastRescan } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

// R12d (design §3.5): the last re-research outcome per watched dossier —
// the automatic Watch re-scan or a reviewer's Research More.
function LastRescanCell({ last }: { last: LastRescan | null }) {
  if (!last) return <span className="text-neutral-400">never</span>;
  const when = new Date(last.at);
  const detail = last.outcome === "failed" ? last.error : last.reason;
  return (
    <div className="flex flex-col gap-0.5" title={detail ?? undefined}>
      <span className="flex items-center gap-2">
        <StatusBadge status={last.outcome} />
        <span className="text-neutral-500" title={when.toLocaleString()}>
          {when.toLocaleDateString()}
        </span>
        {last.trigger === "research_more" && (
          <span className="text-xs text-neutral-400">via Research More</span>
        )}
      </span>
      {detail && (
        <span className="max-w-xs truncate text-xs text-neutral-500">{detail}</span>
      )}
    </div>
  );
}

function isOverdue(nextRecheckAt: string | null): boolean {
  if (!nextRecheckAt) return false;
  return new Date(nextRecheckAt) < new Date();
}

function formatRelative(dateStr: string | null): string {
  if (!dateStr) return "--";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
  if (diffDays === 0) return "today";
  if (diffDays === 1) return "tomorrow";
  return `in ${diffDays}d`;
}

export function RescanPage() {
  const { data, isLoading, error } = useWatchingDossiers();

  const overdueCount = data?.filter((d) => isOverdue(d.next_recheck_at)).length ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Re-scan Schedule</h1>
        {data && data.length > 0 && (
          <div className="flex items-center gap-3 text-sm text-neutral-500">
            <span>{data.length} watching</span>
            {overdueCount > 0 && (
              <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">
                {overdueCount} overdue
              </span>
            )}
          </div>
        )}
      </div>

      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}
      {data && data.length === 0 && (
        <EmptyState>No dossiers are currently in watching status.</EmptyState>
      )}
      {data && data.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-4 py-2 font-medium">Creator</th>
                <th className="px-4 py-2 font-medium">Niche</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Last Generated</th>
                <th className="px-4 py-2 font-medium">Next Re-scan</th>
                <th className="px-4 py-2 font-medium">Last Re-scan</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => {
                const overdue = isOverdue(d.next_recheck_at);
                return (
                  <tr
                    key={d.id}
                    className={`border-b border-neutral-100 last:border-0 dark:border-neutral-900 ${
                      overdue ? "bg-red-50 dark:bg-red-950/30" : ""
                    }`}
                  >
                    <td className="px-4 py-2.5 font-medium">{d.creator_name}</td>
                    <td className="px-4 py-2.5 text-neutral-500">{d.niche_name}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="px-4 py-2.5 text-neutral-500">
                      {new Date(d.generated_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-2.5">
                      {d.next_recheck_at ? (
                        <span
                          className={
                            overdue
                              ? "font-medium text-red-600 dark:text-red-400"
                              : "text-neutral-500"
                          }
                          title={new Date(d.next_recheck_at).toLocaleString()}
                        >
                          {formatRelative(d.next_recheck_at)}
                        </span>
                      ) : (
                        <span className="text-neutral-400">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <LastRescanCell last={d.last_rescan} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
