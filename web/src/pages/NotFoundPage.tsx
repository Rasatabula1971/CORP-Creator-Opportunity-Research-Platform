import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";

export function NotFoundPage() {
  return (
    <EmptyState>
      <p className="mb-3">Page not found.</p>
      <Link to="/" className="text-sm font-medium underline">
        Back to Creators
      </Link>
    </EmptyState>
  );
}
