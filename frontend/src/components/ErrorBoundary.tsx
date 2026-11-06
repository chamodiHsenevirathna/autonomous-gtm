import { Component, type ReactNode } from 'react';

export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="state error" role="alert" style={{ margin: '2rem auto', maxWidth: 640 }}>
        <strong>The page crashed.</strong> {this.state.error.message}
        <p><button type="button" className="btn" onClick={() => location.reload()}>Reload</button></p>
      </div>
    );
  }
}
