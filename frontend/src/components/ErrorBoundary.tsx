import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Top-level error boundary. Without one, any uncaught render error blanks the
 * whole SPA with no recovery path. This catches it and shows a recoverable
 * fallback instead. React requires this to be a class component.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface for debugging; a hosted app could forward this to a reporter.
    console.error("Unhandled UI error:", error, info);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="mx-auto max-w-md px-6 py-16 text-center">
          <h1 className="text-lg font-semibold">Something went wrong</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            An unexpected error occurred. Reloading the page usually fixes it.
          </p>
          <Button className="mt-4" onClick={this.handleReload}>
            Reload
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
