import { useJobs } from "../api/hooks";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

export function JobsPage() {
  const { data, isLoading, error } = useJobs();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Jobs</h1>
      <p className="text-xs text-neutral-500">
        In-memory on the API process — refreshes every few seconds.
      </p>
      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}
      {data && data.length === 0 && <EmptyState>No jobs yet.</EmptyState>}
      {data && data.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-4 py-2 font-medium">Job</th>
                <th className="px-4 py-2 font-medium">Kind</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {data.map((j) => (
                <tr
                  key={j.id}
                  className="border-b border-neutral-100 last:border-0 dark:border-neutral-900"
                >
                  <td className="px-4 py-2.5 font-mono text-xs">{j.id.slice(0, 8)}</td>
                  <td className="px-4 py-2.5 text-neutral-500">{j.kind}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-2.5 text-neutral-500">
                    {new Date(j.created_at).toLocaleString()}
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
