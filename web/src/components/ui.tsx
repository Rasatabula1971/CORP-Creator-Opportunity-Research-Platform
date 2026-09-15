import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-10 text-sm text-neutral-400">
      Loading…
    </div>
  );
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : String(error);
  return (
    <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      {message}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-neutral-300 px-4 py-10 text-center text-sm text-neutral-400 dark:border-neutral-700">
      {children}
    </div>
  );
}

const badgeColors: Record<string, string> = {
  discovered: "bg-neutral-200 text-neutral-700",
  collecting: "bg-blue-100 text-blue-800",
  extracting: "bg-blue-100 text-blue-800",
  clustering: "bg-blue-100 text-blue-800",
  classifying: "bg-blue-100 text-blue-800",
  scoring: "bg-blue-100 text-blue-800",
  human_review: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  watching: "bg-purple-100 text-purple-800",
  queued: "bg-neutral-200 text-neutral-700",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-amber-100 text-amber-800",
  draft: "bg-neutral-200 text-neutral-700",
  active: "bg-blue-100 text-blue-800",
  paused: "bg-amber-100 text-amber-800",
  candidate: "bg-sky-100 text-sky-800",
  canonical: "bg-indigo-100 text-indigo-800",
  verified: "bg-teal-100 text-teal-800",
  qualified: "bg-cyan-100 text-cyan-800",
  selected: "bg-green-100 text-green-800",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = badgeColors[status] ?? "bg-neutral-200 text-neutral-700";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900 ${className}`}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const variants = {
    primary: "bg-neutral-900 text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900",
    secondary:
      "border border-neutral-300 text-neutral-900 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-800",
    danger: "bg-red-600 text-white hover:bg-red-700",
  };
  return (
    <button
      {...props}
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}
