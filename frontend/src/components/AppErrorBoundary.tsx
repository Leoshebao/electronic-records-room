import React from 'react'
import { Button, Result, Space, Typography } from 'antd'

interface Props {
  children: React.ReactNode
  /** 出现异常时的提示语，默认「页面渲染出错」 */
  title?: string
}

interface State {
  error: Error | null
}

/**
 * 全局错误边界：捕获子树渲染异常，避免单个组件抛错导致整棵 React 树卸载（白屏）。
 * 用法：包裹路由出口（内容区）以保留侧栏与顶栏，或包裹 Routes 作为兜底。
 */
export class AppErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 保留堆栈便于排障；生产环境可在此接入日志上报
    console.error('[AppErrorBoundary]', error, info.componentStack)
  }

  private handleRetry = () => {
    this.setState({ error: null })
  }

  private handleHome = () => {
    window.location.href = '/'
  }

  render() {
    const { error } = this.state
    if (error) {
      return (
        <Result
          status="warning"
          title={this.props.title || '页面渲染出错'}
          subTitle={error.message}
          extra={
            <Space>
              <Button type="primary" onClick={this.handleRetry}>
                重试
              </Button>
              <Button onClick={this.handleHome}>返回首页</Button>
            </Space>
          }
        >
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            异常已被隔离，侧边导航仍可继续使用；若反复出现请截图控制台报错反馈。
          </Typography.Paragraph>
        </Result>
      )
    }
    return this.props.children
  }
}

export default AppErrorBoundary
