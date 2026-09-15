import { useResearchRuns } from "../api/hooks";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

export function RunsPage() {
  const { data, isLoading, error } = useResearchRuns();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Research Runs</h1>
      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}
      {data && data.length === 0 && <EmptyState>No research runs yet.</EmptyState>}
      {data && data.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-4 py-2 font-medium">Run</th>
                <th className="px-4 py-2 font-medium">Scope</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Started</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                >
                  <td className="px-4 py-2.5 font-mono text-xs">{r.id.slice(0, 8)}</td>
                  <td className="px-4 py-2.5 text-neutral-500">{r.scope}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-2.5 text-neutral-500">
                    {new Date(r.started_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
