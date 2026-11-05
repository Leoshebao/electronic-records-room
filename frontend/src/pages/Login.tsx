import React, { useState } from 'react'
import { Button, Card, Form, Input, Typography, Alert, message } from 'antd'
import { LockOutlined, UserOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { APP_NAME } from '../api/client'

const Login: React.FC = () => {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: string } }
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [msgApi, holder] = message.useMessage()

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      const user = await login(values.username.trim(), values.password)
      msgApi.success(`欢迎，${user.full_name}`)
      if (user.must_change_password) navigate('/change-password', { replace: true })
      else navigate(location.state?.from || '/', { replace: true })
    } catch (e) {
      setError((e as Error).message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      {holder}
      <Card className="login-card" bordered={false}>
        <div className="login-title">
          <SafetyCertificateOutlined style={{ fontSize: 32, color: '#1f5aa6' }} />
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>
              {APP_NAME}
            </Typography.Title>
            <Typography.Text type="secondary">内网档案资料统一管理与借阅平台</Typography.Text>
          </div>
        </div>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={onFinish} size="large" requiredMark={false}>
          <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserOutlined />} placeholder="请输入账号" autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
          首次登录请使用管理员分配的初始密码，登录后需立即修改。连续输错将临时锁定账号。
        </Typography.Paragraph>
      </Card>
      <div className="login-footer">仅限内网访问 · 所有操作留痕审计</div>
    </div>
  )
}

export default Login
