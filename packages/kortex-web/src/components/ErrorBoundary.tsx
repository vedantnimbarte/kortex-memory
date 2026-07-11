import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/** Catches render-time crashes so a broken screen degrades to a message with a
 *  way out, instead of a blank page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid min-h-screen place-items-center px-6">
        <div className="max-w-md text-center">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-copper">Something broke</p>
          <h1 className="mt-3 text-xl font-semibold text-ink">This screen hit an error.</h1>
          <p className="mt-2 text-sm text-muted">
            The rest of the app is fine. Reload to get back to work.
          </p>
          <button
            onClick={() => {
              this.setState({ error: null });
              window.location.assign("/app");
            }}
            className="mt-6 rounded-md bg-copper px-4 py-2 text-sm font-medium text-[#1a0e02] hover:bg-copper-bright"
          >
            Back to app
          </button>
        </div>
      </div>
    );
  }
}
