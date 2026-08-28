import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Keeps one broken panel from taking down the console.
 *
 * Scoped per region rather than wrapped once around the app: if the
 * contribution chart throws, the analyst should lose the contribution chart,
 * not the probability, the evidence and the provenance beside it.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; label: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}] render failed`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-lg border border-alert-500/40 bg-alert-500/5 p-4 text-sm" role="alert">
          <p className="font-semibold">{this.props.label} could not be displayed.</p>
          <p className="mt-1 muted">
            The rest of this page is unaffected. Nothing is shown here in place of the missing panel.
          </p>
          <p className="mt-2 font-mono text-2xs">{this.state.error.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}
