import React, { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { http, normalizeError } from '../api/client'

/** 首次登录/管理员重置后的强制改密页：成功后强制重新登录，避免旧 token 继续有效 */
const ChangePassword: React.FC = () => {
  const { user, logout, refreshMe } = useAuth()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()

  const onFinish = async (values: { old_password: string; new_password: string }) => {
    setLoading(true)
    try {
      await http.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      msgApi.success('密码修改成功，请用新密码重新登录')
      await logout()
      navigate('/login', { replace: true })
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      {holder}
      <Card className="login-card" bordered={false}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          修改登录密码
        </Typography.Title>
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={user?.must_change_password ? '首次登录（或密码被重置）需先修改密码' : '定期更换密码有助于账号安全'}
        />
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, max: 64, message: '长度为 8-64 位' },
              { pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/, message: '需同时包含字母与数字' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value) =>
                  !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入不一致')),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            提交并重新登录
          </Button>
          {!user?.must_change_password && (
            <Button
              type="link"
              block
              style={{ marginTop: 8 }}
              onClick={async () => {
                await refreshMe()
                navigate('/', { replace: true })
              }}
            >
              暂不修改，返回系统
            </Button>
          )}
        </Form>
      </Card>
    </div>
  )
}

export default ChangePassword
