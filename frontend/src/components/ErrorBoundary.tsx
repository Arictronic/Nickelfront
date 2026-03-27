import { Component, type ReactNode } from "react";

type Props = {
  name?: string;
  children: ReactNode;
};

type State = {
  hasError: boolean;
  message?: string;
};

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error?.message || "Unknown error" };
  }

  componentDidCatch(error: Error) {
    // eslint-disable-next-line no-console
    console.error("[UI ErrorBoundary]", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="page">
          <div className="panel">
            <h3>Ошибка в разделе {this.props.name || "страницы"}</h3>
            <p className="error">{this.state.message}</p>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
