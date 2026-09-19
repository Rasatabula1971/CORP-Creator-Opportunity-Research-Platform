import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCampaigns, useCreateCampaign } from "../api/hooks";
import { Button, Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "../components/ui";

export function CampaignsPage() {
  const { data, isLoading, error } = useCampaigns();
  const [showForm, setShowForm] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Campaigns</h1>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "New Campaign"}
        </Button>
      </div>

      {showForm && (
        <CreateCampaignForm
          onDone={(id) => {
            setShowForm(false);
            navigate(`/campaigns/${id}`);
          }}
        />
      )}

      {isLoading && <Spinner />}
      {error && <ErrorBanner error={error} />}

      {data && data.length === 0 && (
        <EmptyState>No campaigns yet. Create one to get started.</EmptyState>
      )}

      {data && data.length > 0 && (
        <Card className="p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Niches</th>
                <th className="px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/campaigns/${c.id}`)}
                  className="cursor-pointer border-b border-neutral-100 last:border-0 hover:bg-neutral-50 dark:border-neutral-900 dark:hover:bg-neutral-800/50"
                >
                  <td className="px-4 py-2.5 font-medium">{c.name}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-2.5 text-neutral-500">
                    {c.target_niche_count} target
                  </td>
                  <td className="px-4 py-2.5 text-neutral-500">
                    {new Date(c.created_at).toLocaleDateString()}
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

function CreateCampaignForm({ onDone }: { onDone: (id: string) => void }) {
  const create = useCreateCampaign();
  const [name, setName] = useState("");
  const [targetNicheCount, setTargetNicheCount] = useState(10);
  const [creatorsPerNiche, setCreatorsPerNiche] = useState(10);
  const [minFollowers, setMinFollowers] = useState(10000);
  const [maxFollowers, setMaxFollowers] = useState(200000);
  const [validationError, setValidationError] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (targetNicheCount < 1 || creatorsPerNiche < 1) {
      setValidationError("Target niches and creators per niche must be at least 1.");
      return;
    }
    if (minFollowers < 0 || maxFollowers < 0) {
      setValidationError("Follower counts cannot be negative.");
      return;
    }
    if (minFollowers > maxFollowers) {
      setValidationError("Min followers cannot be greater than max followers.");
      return;
    }
    setValidationError(null);
    create.mutate(
      {
        name,
        target_niche_count: targetNicheCount,
        initial_creators_per_niche: creatorsPerNiche,
        creator_min_followers: minFollowers,
        creator_max_followers: maxFollowers,
      },
      { onSuccess: (campaign) => onDone(campaign.id) },
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-500">
            Campaign Name
          </label>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Target Niches
            </label>
            <input
              type="number"
              min={1}
              value={targetNicheCount}
              onChange={(e) => setTargetNicheCount(Number(e.target.value))}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Creators per Niche
            </label>
            <input
              type="number"
              min={1}
              value={creatorsPerNiche}
              onChange={(e) => setCreatorsPerNiche(Number(e.target.value))}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Min Followers
            </label>
            <input
              type="number"
              min={0}
              value={minFollowers}
              onChange={(e) => setMinFollowers(Number(e.target.value))}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">
              Max Followers
            </label>
            <input
              type="number"
              min={0}
              value={maxFollowers}
              onChange={(e) => setMaxFollowers(Number(e.target.value))}
              className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            />
          </div>
        </div>

        {validationError && <ErrorBanner error={validationError} />}
        {create.error && <ErrorBanner error={create.error} />}

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating..." : "Create Campaign"}
        </Button>
      </form>
    </Card>
  );
}
