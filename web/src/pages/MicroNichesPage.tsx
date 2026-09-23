import { useState } from "react";
import { Link } from "react-router-dom";
import {
  useApproveMicroNiche,
  useMicroNiches,
  useRejectMicroNiche,
  useSuggestMicroNiches,
} from "../api/hooks";
import type { MicroNiche, MicroNicheStatus } from "../api/types";
import { Button, Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

// Creator-first discovery: problems from researched creators' audiences,
// proposed as niche seeds. Nothing is drilled — and no LLM quota is spent —
// until a suggestion is approved here.

const TABS: { status: MicroNicheStatus; label: string }[] = [
  { status: "pending", label: "Pending" },
  { status: "approved", label: "Approved" },
  { status: "rejected", label: "Rejected" },
];

function formatFollowers(n: number | null): string {
  if (n == null) return "unknown size";
  if (n >= 1000) return `${Math.round(n / 1000)}K followers`;
  return `${n} followers`;
}

function PendingRow({ item }: { item: MicroNiche }) {
  // Cluster labels are problem-shaped ("how do I stop oak going grey");
  // the reviewer can reword one into a searchable niche before approving.
  const [topic, setTopic] = useState(item.label);
  const approve = useApproveMicroNiche();
  const reject = useRejectMicroNiche();
  const busy = approve.isPending || reject.isPending;
  const edited = topic.trim() !== item.label.trim();

  return (
    <tr className="border-b border-neutral-100 align-top last:border-0 dark:border-neutral-900">
      <td className="px-4 py-3">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          aria-label={`Topic to drill for ${item.label}`}
          className="w-full rounded-md border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-950"
        />
        {edited && (
          <div className="mt-1 text-xs text-neutral-500">
            Audience wording: <span className="italic">{item.label}</span>
          </div>
        )}
        {(approve.error || reject.error) && (
          <div className="mt-2">
            <ErrorBanner error={approve.error ?? reject.error} />
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-neutral-600 dark:text-neutral-400">
        {item.source_creator_count} creator{item.source_creator_count === 1 ? "" : "s"}
        <div className="text-xs text-neutral-500">{item.total_frequency} mentions</div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-neutral-600 dark:text-neutral-400">
        {item.creator_id ? (
          <Link to={`/creators/${item.creator_id}`} className="hover:underline">
            {item.creator_niche ?? "creator"}
          </Link>
        ) : (
          (item.creator_niche ?? "--")
        )}
        <div className="text-xs text-neutral-500">{formatFollowers(item.follower_count)}</div>
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-2 whitespace-nowrap">
          <Button
            disabled={busy || !topic.trim()}
            onClick={() =>
              approve.mutate({ id: item.id, topic: edited ? topic.trim() : undefined })
            }
            title="Starts a niche drill for this topic (uses LLM quota)"
          >
            {approve.isPending ? "Starting…" : "Approve & drill"}
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => reject.mutate(item.id)}>
            Reject
          </Button>
        </div>
      </td>
    </tr>
  );
}

function DecidedRow({ item }: { item: MicroNiche }) {
  return (
    <tr className="border-b border-neutral-100 last:border-0 dark:border-neutral-900">
      <td className="px-4 py-2.5">
        <div className="font-medium">{item.approved_topic ?? item.label}</div>
        {item.approved_topic && item.approved_topic !== item.label && (
          <div className="text-xs text-neutral-500">from: {item.label}</div>
        )}
        {item.decision_note && (
          <div className="text-xs text-neutral-500">note: {item.decision_note}</div>
        )}
      </td>
      <td className="px-4 py-2.5">
        <StatusBadge status={item.status} />
      </td>
      <td className="px-4 py-2.5 text-neutral-500">
        {item.decided_at ? new Date(item.decided_at).toLocaleString() : "--"}
      </td>
      <td className="px-4 py-2.5 text-right">
        {item.discovery_job_id && (
          <Link to="/jobs" className="text-sm text-neutral-500 hover:underline">
            drill job →
          </Link>
        )}
      </td>
    </tr>
  );
}

export function MicroNichesPage() {
  const [status, setStatus] = useState<MicroNicheStatus>("pending");
  const { data, isLoading, error } = useMicroNiches(status);
  const suggest = useSuggestMicroNiches();

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Micro-niches</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Recurring problems in researched creators' audiences (10K–200K followers). Approving
            one drills it as a niche and uses LLM quota; nothing runs until you do. Rejected
            problems are not suggested again.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={suggest.isPending}
          onClick={() => suggest.mutate()}
          title="Re-read researched creators' audience clusters (no LLM cost)"
        >
          {suggest.isPending ? "Refreshing…" : "Refresh suggestions"}
        </Button>
      </div>

      {suggest.data && (
        <div className="text-sm text-neutral-500">
          {suggest.data.created} new, {suggest.data.updated} refreshed from{" "}
          {suggest.data.clusters_seen} audience cluster
          {suggest.data.clusters_seen === 1 ? "" : "s"}
          {suggest.data.skipped_already_decided > 0 &&
            ` · ${suggest.data.skipped_already_decided} already decided`}
        </div>
      )}
      {suggest.error && <ErrorBanner error={suggest.error} />}

      <div className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
        {TABS.map((t) => (
          <button
            key={t.status}
            onClick={() => setStatus(t.status)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              status === t.status
                ? "border-neutral-900 dark:border-neutral-100"
                : "border-transparent text-neutral-500 hover:text-neutral-800"
            }`}
          >
            {t.label}
            {status === t.status && data ? ` (${data.totalCount})` : ""}
          </button>
        ))}
      </div>

      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}
      {data && data.items.length === 0 && (
        <EmptyState>
          {status === "pending"
            ? "No suggestions waiting. They appear after a creator is researched, or press Refresh suggestions."
            : `No ${status} micro-niches yet.`}
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              {status === "pending" ? (
                <tr>
                  <th className="px-4 py-2 font-medium">Topic to drill</th>
                  <th className="px-4 py-2 font-medium">Seen in</th>
                  <th className="px-4 py-2 font-medium">Top source</th>
                  <th className="px-4 py-2" />
                </tr>
              ) : (
                <tr>
                  <th className="px-4 py-2 font-medium">Micro-niche</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Decided</th>
                  <th className="px-4 py-2" />
                </tr>
              )}
            </thead>
            <tbody>
              {data.items.map((item) =>
                status === "pending" ? (
                  <PendingRow key={item.id} item={item} />
                ) : (
                  <DecidedRow key={item.id} item={item} />
                ),
              )}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
