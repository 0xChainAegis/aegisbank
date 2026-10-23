import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/**
 * 最后一道防线（UX-33）：任一子组件抛错时不再整页白屏。
 * 展示可操作的恢复入口，并保留错误信息便于定位。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(error: unknown): State {
    const message = error instanceof Error ? error.message : String(error);
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // 前端没有远端日志，至少把上下文留在控制台，便于复现。
    console.error('[AegisBank] 渲染异常', error, info.componentStack);
  }

  private reload = () => {
    if (typeof window !== 'undefined') window.location.reload();
  };

  private reset = () => {
    this.setState({ hasError: false, message: '' });
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="error-boundary" role="alert">
        <div className="card error-boundary-card">
          <span className="eyebrow">RENDER RECOVERY</span>
          <h1>界面遇到异常，操作未被提交</h1>
          <p>
            页面渲染出错，但后端状态机与审计链不受影响。可以先重试渲染；若仍失败，刷新页面并重新执行任务。
          </p>
          <pre className="error-boundary-detail">{this.state.message || '未知渲染错误'}</pre>
          <div className="error-boundary-actions">
            <button className="ghost-button" onClick={this.reset}>
              重试渲染
            </button>
            <button className="primary-button" onClick={this.reload}>
              刷新页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
