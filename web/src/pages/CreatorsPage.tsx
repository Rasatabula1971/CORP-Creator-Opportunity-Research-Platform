import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateCreator, useCreators } from "../api/hooks";
import { Button, Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";
import type { PlatformAccountCreateInput } from "../api/types";

export function CreatorsPage() {
  const { data, isLoading, error } = useCreators();
  const [showForm, setShowForm] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">
          Creators
          {data && data.totalCount > data.items.length
            ? ` (${data.items.length} of ${data.totalCount})`
            : ""}
        </h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "Add Creator"}
        </Button>
      </div>

      {showForm && (
        <AddCreatorForm
          onDone={(id) => {
            setShowForm(false);
            navigate(`/creators/${id}`);
          }}
        />
      )}

      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}

      {data && data.items.length === 0 && (
        <EmptyState>No creators yet. Add one to get started.</EmptyState>
      )}

      {data && data.items.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Niche</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/creators/${c.id}`)}
                  className="cursor-pointer border-b border-neutral-100 last:border-0 hover:bg-neutral-50 dark:border-neutral-900 dark:hover:bg-neutral-800/50"
                >
                  <td className="px-4 py-2.5 font-medium">{c.name}</td>
                  <td className="px-4 py-2.5 text-neutral-500">{c.niche ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-2.5 text-neutral-500">{c.discovery_source ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function AddCreatorForm({ onDone }: { onDone: (id: string) => void }) {
  const create = useCreateCreator();
  const [name, setName] = useState("");
  const [niche, setNiche] = useState("");
  const [accounts, setAccounts] = useState<PlatformAccountCreateInput[]>([
    { platform: "youtube", handle: "" },
  ]);

  function updateAccount(i: number, field: keyof PlatformAccountCreateInput, value: string) {
    setAccounts((prev) => prev.map((a, idx) => (idx === i ? { ...a, [field]: value } : a)));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        name,
        niche: niche || null,
        accounts: accounts.filter((a) => a.handle.trim()),
      },
      { onSuccess: (creator) => onDone(creator.id) },
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-500">Name</label>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-500">
            Niche (optional)
          </label>
          <input
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-500">
            Platform account
          </label>
          {accounts.map((a, i) => (
            <div key={i} className="mb-2 flex gap-2">
              <select
                value={a.platform}
                onChange={(e) => updateAccount(i, "platform", e.target.value)}
                className="rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              >
                <option value="youtube">YouTube</option>
                <option value="reddit">Reddit</option>
                <option value="tiktok">TikTok</option>
                <option value="web">Web (creator page)</option>
              </select>
              <input
                placeholder="@handle or URL"
                value={a.handle}
                onChange={(e) => updateAccount(i, "handle", e.target.value)}
                className="flex-1 rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setAccounts((prev) => [...prev, { platform: "youtube", handle: "" }])}
            className="text-xs font-medium text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            + add another account
          </button>
        </div>

        {create.error && <ErrorBanner error={create.error} />}

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create Creator"}
        </Button>
      </form>
    </Card>
  );
}
