import React, { useEffect, useState } from 'react'
import { Layout, Menu, Dropdown, Avatar, Space, Tag, Modal, Form, Input, message, Typography } from 'antd'
import {
  DashboardOutlined,
  FileTextOutlined,
  SearchOutlined,
  SwapOutlined,
  ApartmentOutlined,
  TeamOutlined,
  SafetyCertificateOutlined,
  CloudServerOutlined,
  HeartOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  DownOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { APP_NAME, http, normalizeError } from '../api/client'
import { AppErrorBoundary } from '../components/AppErrorBoundary'

const { Header, Sider, Content } = Layout

interface NavItem {
  key: string
  label: string
  icon: React.ReactNode
  permission?: string
}

const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '概览', icon: <DashboardOutlined /> },
  { key: '/documents', label: '资料库', icon: <FileTextOutlined />, permission: 'doc:view' },
  { key: '/search', label: '全文检索', icon: <SearchOutlined />, permission: 'doc:view' },
  { key: '/borrow', label: '借阅管理', icon: <SwapOutlined />, permission: 'borrow:apply' },
  { key: '/rooms', label: '资料室与类目', icon: <ApartmentOutlined />, permission: 'room:manage' },
  { key: '/users', label: '用户与部门', icon: <TeamOutlined />, permission: 'user:manage' },
  { key: '/audit', label: '审计日志', icon: <SafetyCertificateOutlined />, permission: 'audit:view' },
  { key: '/backups', label: '备份管理', icon: <CloudServerOutlined />, permission: 'backup:manage' },
  { key: '/health', label: '系统自检', icon: <HeartOutlined /> },
]

export const AppLayout: React.FC = () => {
  const { user, logout, has, refreshMe } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdForm] = Form.useForm()
  const [pwdLoading, setPwdLoading] = useState(false)
  const [msgApi, msgHolder] = message.useMessage()

  useEffect(() => {
    if (user?.must_change_password && location.pathname !== '/change-password') {
      navigate('/change-password', { replace: true })
    }
  }, [user?.must_change_password, location.pathname, navigate])

  const items = NAV_ITEMS.filter((i) => !i.permission || has(i.permission)).map((i) => ({
    key: i.key,
    icon: i.icon,
    label: i.label,
  }))

  const selectedKey =
    NAV_ITEMS.map((i) => i.key)
      .filter((k) => k !== '/' && location.pathname.startsWith(k))
      .sort((a, b) => b.length - a.length)[0] || '/'

  const submitPassword = async () => {
    try {
      const values = await pwdForm.validateFields()
      setPwdLoading(true)
      await http.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      msgApi.success('密码已修改，请重新登录')
      setPwdOpen(false)
      pwdForm.resetFields()
      await logout()
      navigate('/login', { replace: true })
    } catch (e) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    } finally {
      setPwdLoading(false)
    }
  }

  const onMenuClick = async ({ key }: { key: string }) => {
    if (key === 'logout') {
      Modal.confirm({
        title: '确认退出登录？',
        onOk: async () => {
          await logout()
          navigate('/login', { replace: true })
        },
      })
      return
    }
    if (key === 'password') {
      setPwdOpen(true)
      return
    }
    if (key === 'refresh') {
      await refreshMe()
      msgApi.success('用户信息已刷新')
      return
    }
    navigate(key)
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {msgHolder}
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark" width={216}>
        <div className="app-logo">
          <SafetyCertificateOutlined />
          {!collapsed && <span>{APP_NAME}</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={items}
          onClick={onMenuClick}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Typography.Text strong style={{ fontSize: 16 }}>
            {NAV_ITEMS.find((i) => i.key === selectedKey)?.label || APP_NAME}
          </Typography.Text>
          <Dropdown
            menu={{
              items: [
                { key: 'refresh', label: '刷新用户信息', icon: <UserOutlined /> },
                { key: 'password', label: '修改密码', icon: <KeyOutlined /> },
                { type: 'divider' as const },
                { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, danger: true },
              ],
              onClick: onMenuClick,
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.full_name || user?.username}</span>
              <Tag color="blue">{user?.role_label}</Tag>
              {user?.department_name && <Tag>{user.department_name}</Tag>}
              <DownOutlined style={{ fontSize: 10 }} />
            </Space>
          </Dropdown>
        </Header>
        <Content className="app-content">
          <AppErrorBoundary key={location.pathname}>
            <Outlet />
          </AppErrorBoundary>
        </Content>
      </Layout>

      <Modal
        title="修改密码"
        open={pwdOpen}
        onCancel={() => setPwdOpen(false)}
        onOk={submitPassword}
        confirmLoading={pwdLoading}
        okText="提交"
        destroyOnClose
      >
        <Form form={pwdForm} layout="vertical" preserve={false}>
          <Form.Item
            name="old_password"
            label="原密码"
            rules={[{ required: true, message: '请输入原密码' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '至少 8 位' },
              {
                pattern: /^(?=.*[A-Za-z])(?=.*\d).+$/,
                message: '需同时包含字母与数字',
              },
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
        </Form>
      </Modal>
    </Layout>
  )
}
