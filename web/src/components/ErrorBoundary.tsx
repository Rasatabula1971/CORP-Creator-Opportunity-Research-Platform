import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled error in component tree:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-xl px-4 py-16 text-center">
          <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
            Something went wrong.
          </p>
          <p className="mt-1 text-sm text-neutral-500">{this.state.error.message}</p>
          <button
            type="button"
            onClick={() => window.location.assign("/")}
            className="mt-4 rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Back to Creators
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
