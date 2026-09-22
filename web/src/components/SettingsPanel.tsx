import { useState } from "react";
import { getApiBase, getApiKey, setApiBase, setApiKey } from "../api/client";

export function SettingsPanel() {
  const [open, setOpen] = useState(false);
  const [base, setBase] = useState(getApiBase());
  const [key, setKey] = useState(getApiKey());

  function save() {
    setApiBase(base.trim());
    setApiKey(key.trim());
    setOpen(false);
    window.location.reload();
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-md px-3 py-2 text-sm font-medium hover:bg-neutral-100 dark:hover:bg-neutral-800"
      >
        Settings
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-80 rounded-lg border border-neutral-200 bg-white p-4 shadow-lg dark:border-neutral-800 dark:bg-neutral-900">
          <label className="mb-1 block text-xs font-medium text-neutral-500">API base URL</label>
          <input
            value={base}
            onChange={(e) => setBase(e.target.value)}
            placeholder="http://localhost:8010"
            className="mb-3 w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
          <label className="mb-1 block text-xs font-medium text-neutral-500">API key</label>
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="leave blank if API_KEY is unset"
            className="mb-3 w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          />
          <button
            onClick={save}
            className="w-full rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-neutral-100 dark:text-neutral-900"
          >
            Save & reload
          </button>
        </div>
      )}
    </div>
  );
}
