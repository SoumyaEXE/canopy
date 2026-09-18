import { Component, type ErrorInfo, type ReactNode } from "react";
import { RiErrorWarningLine, RiRefreshLine } from "@remixicon/react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Catches runtime errors in <MapView> (e.g. MapLibre GL init failures)
 * so they don't unmount the entire React tree.
 */
export class MapErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[MapErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-background-secondary-default p-6 text-center">
          <RiErrorWarningLine className="size-10 text-text-tertiary" />
          <div className="flex flex-col gap-1">
            <p className="text-body-2-medium text-text-primary">Map failed to load</p>
            <p className="max-w-xs text-caption-1-regular text-text-tertiary">
              {this.state.error?.message ?? "An unexpected error occurred while initialising the map."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-border-button-default bg-background-primary-default px-3 py-1.5 text-body-2-medium text-text-primary shadow-xs transition-colors hover:bg-background-primary-hover"
          >
            <RiRefreshLine className="size-4" />
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
