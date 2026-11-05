import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, Modal, Popconfirm, Row, Select, Space, Switch, Table, Tabs, Tag,
  Typography, message, Alert, Descriptions,
} from 'antd'
import { PlusOutlined, ReloadOutlined, KeyOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { http, normalizeError } from '../api/client'
import { ROLE_LABELS, type Department, type Role, type UserOut } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as Role[]).map((v) => ({ value: v, label: ROLE_LABELS[v] }))

const fmt = (v?: string | null) => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const Users: React.FC = () => {
  const { user: me } = useAuth()
  const [msgApi, holder] = message.useMessage()
  const [tab, setTab] = useState('users')

  const [rows, setRows] = useState<UserOut[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [role, setRole] = useState<string | undefined>()
  const [activeFilter, setActiveFilter] = useState<boolean | undefined>()
  const [loading, setLoading] = useState(false)

  const [depts, setDepts] = useState<Department[]>([])
  const [deptLoading, setDeptLoading] = useState(false)
  const [deptModal, setDeptModal] = useState(false)
  const [deptForm] = Form.useForm()

  const [userModal, setUserModal] = useState<{ open: boolean; user?: UserOut }>({ open: false })
  const [userForm] = Form.useForm()
  const [pwdResult, setPwdResult] = useState<{ title: string; username: string; password: string } | null>(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<{ total: number; items: UserOut[] }>('/users', {
        params: {
          keyword: keyword || undefined,
          role,
          is_active: activeFilter,
          page,
          page_size: pageSize,
        },
      })
      setRows(data.items)
      setTotal(data.total)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [keyword, role, activeFilter, page, pageSize, msgApi])

  const loadDepts = useCallback(async () => {
    setDeptLoading(true)
    try {
      const { data } = await http.get<Department[]>('/departments')
      setDepts(data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setDeptLoading(false)
    }
  }, [msgApi])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  useEffect(() => {
    void loadDepts()
  }, [loadDepts])

  const openUserModal = (u?: UserOut) => {
    setUserModal({ open: true, user: u })
    userForm.setFieldsValue(
      u
        ? {
            full_name: u.full_name,
            role: u.role,
            department_id: u.department_id ?? undefined,
            email: u.email ?? undefined,
            phone: u.phone ?? undefined,
            is_active: u.is_active,
          }
        : { role: 'viewer' },
    )
  }

  const submitUser = async () => {
    try {
      const v = await userForm.validateFields()
      if (userModal.user) {
        await http.patch(`/users/${userModal.user.id}`, v)
        msgApi.success('用户信息已更新')
      } else {
        const { data } = await http.post<UserOut & { initial_password?: string }>('/users', v)
        msgApi.success('用户已创建')
        if (data.initial_password) {
          setPwdResult({
            title: '账号创建成功，请把初始密码转告本人',
            username: data.username,
            password: data.initial_password,
          })
        }
      }
      setUserModal({ open: false })
      void loadUsers()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    }
  }

  const submitDept = async () => {
    try {
      const v = await deptForm.validateFields()
      // 后端部门创建接口使用查询参数
      await http.post('/departments', null, {
        params: { name: v.name, code: v.code || undefined, parent_id: v.parent_id || undefined },
      })
      msgApi.success('部门已创建')
      setDeptModal(false)
      void loadDepts()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Card size="small" bodyStyle={{ paddingBottom: 0 }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'users',
              label: '用户账号',
              children: (
                <>
                  <Row gutter={[8, 8]} style={{ marginBottom: 8 }}>
                    <Col xs={24} md={6}>
                      <Input.Search
                        allowClear
                        placeholder="登录名 / 姓名"
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                        onSearch={() => setPage(1)}
                      />
                    </Col>
                    <Col xs={12} md={4}>
                      <Select
                        allowClear
                        placeholder="角色"
                        style={{ width: '100%' }}
                        value={role}
                        onChange={(v) => {
                          setRole(v)
                          setPage(1)
                        }}
                        options={ROLE_OPTIONS}
                      />
                    </Col>
                    <Col xs={12} md={4}>
                      <Select
                        allowClear
                        placeholder="状态"
                        style={{ width: '100%' }}
                        value={activeFilter}
                        onChange={(v) => {
                          setActiveFilter(v)
                          setPage(1)
                        }}
                        options={[
                          { value: true, label: '已启用' },
                          { value: false, label: '已停用' },
                        ]}
                      />
                    </Col>
                    <Col xs={12} md={3}>
                      <Button icon={<ReloadOutlined />} block onClick={() => void loadUsers()}>
                        刷新
                      </Button>
                    </Col>
                    <Col xs={12} md={4}>
                      <Button type="primary" icon={<PlusOutlined />} block onClick={() => openUserModal()}>
                        新建用户
                      </Button>
                    </Col>
                  </Row>
                  <Table
                    rowKey="id"
                    size="small"
                    loading={loading}
                    dataSource={rows}
                    scroll={{ x: 1100 }}
                    pagination={{
                      current: page,
                      pageSize,
                      total,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 个账号`,
                      onChange: (p, s) => {
                        setPage(p)
                        setPageSize(s)
                      },
                    }}
                    columns={[
                      {
                        title: '登录名',
                        dataIndex: 'username',
                        width: 140,
                        render: (v, r) => (
                          <Space size={4}>
                            <span>{v}</span>
                            {r.id === me?.id && <Tag color="blue">我</Tag>}
                          </Space>
                        ),
                      },
                      { title: '姓名', dataIndex: 'full_name', width: 110 },
                      {
                        title: '角色',
                        dataIndex: 'role',
                        width: 110,
                        render: (v: Role) => <Tag color={v === 'sysadmin' ? 'red' : v === 'records_manager' ? 'blue' : 'default'}>{ROLE_LABELS[v]}</Tag>,
                      },
                      { title: '部门', dataIndex: 'department_name', width: 130, render: (v) => v || '-' },
                      { title: '手机', dataIndex: 'phone', width: 120, render: (v) => v || '-' },
                      {
                        title: '状态',
                        dataIndex: 'is_active',
                        width: 90,
                        render: (v: boolean, r) => (
                          <Space size={2}>
                            <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
                            {r.must_change_password && <Tag color="orange">待改密</Tag>}
                          </Space>
                        ),
                      },
                      { title: '最近登录', dataIndex: 'last_login_at', width: 140, render: fmt },
                      {
                        title: '操作',
                        width: 190,
                        fixed: 'right',
                        render: (_v, r) => (
                          <Space size={0}>
                            <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openUserModal(r)}>
                              编辑
                            </Button>
                            <Popconfirm
                              title="重置该用户密码？"
                              description="将生成随机密码，用户下次登录须修改"
                              onConfirm={async () => {
                                try {
                                  const { data } = await http.post<{ new_password: string; message: string }>(
                                    `/users/${r.id}/reset-password`,
                                  )
                                  setPwdResult({
                                    title: '密码已重置，请把新密码转告本人',
                                    username: r.username,
                                    password: data.new_password,
                                  })
                                } catch (e) {
                                  msgApi.error(normalizeError(e).message)
                                }
                              }}
                            >
                              <Button size="small" type="link" icon={<KeyOutlined />}>
                                重置
                              </Button>
                            </Popconfirm>
                            <Popconfirm
                              title="删除该用户？"
                              description="逻辑删除，历史审计记录保留"
                              okButtonProps={{ danger: true }}
                              onConfirm={async () => {
                                try {
                                  await http.delete(`/users/${r.id}`)
                                  msgApi.success('已删除')
                                  void loadUsers()
                                } catch (e) {
                                  msgApi.error(normalizeError(e).message)
                                }
                              }}
                              disabled={r.id === me?.id}
                            >
                              <Button size="small" type="link" danger icon={<DeleteOutlined />} disabled={r.id === me?.id} />
                            </Popconfirm>
                          </Space>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'depts',
              label: '部门管理',
              children: (
                <>
                  <Space style={{ marginBottom: 8 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setDeptModal(true)}>
                      新建部门
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={() => void loadDepts()}>
                      刷新
                    </Button>
                    <Typography.Text type="secondary">
                      部门用于标识资料归属，不作为权限边界（权限由角色 + 密级决定）
                    </Typography.Text>
                  </Space>
                  <Table
                    rowKey="id"
                    size="small"
                    loading={deptLoading}
                    dataSource={depts}
                    pagination={false}
                    columns={[
                      { title: '部门名称', dataIndex: 'name' },
                      { title: '编码', dataIndex: 'code', width: 140, render: (v) => v || '-' },
                      {
                        title: '上级部门',
                        dataIndex: 'parent_id',
                        width: 160,
                        render: (v: number | null) => (v ? depts.find((d) => d.id === v)?.name || v : '—'),
                      },
                      { title: '排序', dataIndex: 'sort_order', width: 80, align: 'center' },
                      {
                        title: '状态',
                        dataIndex: 'is_active',
                        width: 90,
                        render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>,
                      },
                    ]}
                  />
                </>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={userModal.user ? `编辑用户 - ${userModal.user.full_name}` : '新建用户'}
        open={userModal.open}
        onCancel={() => setUserModal({ open: false })}
        onOk={submitUser}
        okText="保存"
        width={560}
        destroyOnClose
      >
        <Form form={userForm} layout="vertical" preserve={false}>
          {!userModal.user && (
            <Form.Item
              name="username"
              label="登录名"
              rules={[
                { required: true, message: '请输入登录名' },
                { min: 3, message: '至少 3 位' },
                { pattern: /^[A-Za-z0-9_.-]+$/, message: '仅字母、数字、下划线、点、短横线' },
              ]}
            >
              <Input maxLength={64} placeholder="如：zhangsan" />
            </Form.Item>
          )}
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item name="full_name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
                <Input maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="role" label="角色" rules={[{ required: true }]}>
                <Select options={ROLE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item name="department_id" label="部门">
                <Select
                  allowClear
                  placeholder="可选"
                  options={depts.map((d) => ({ value: d.id, label: d.name }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="phone" label="手机号">
                <Input maxLength={20} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="email" label="邮箱">
            <Input maxLength={100} type="email" />
          </Form.Item>
          {!userModal.user && (
            <Form.Item name="password" label="初始密码" tooltip="留空则系统随机生成并显示一次">
              <Input.Password maxLength={64} placeholder="至少 8 位，含字母和数字；留空自动生成" />
            </Form.Item>
          )}
          {userModal.user && (
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title="重置结果"
        open={!!pwdResult}
        onCancel={() => setPwdResult(null)}
        onOk={() => setPwdResult(null)}
        okText="我已记录"
        cancelButtonProps={{ style: { display: 'none' } }}
      >
        {pwdResult && (
          <>
            <Alert type="warning" showIcon message={pwdResult.title} style={{ marginBottom: 12 }} />
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="登录名">
                <Typography.Text copyable>{pwdResult.username}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="密码">
                <Typography.Text copyable strong style={{ fontFamily: 'monospace' }}>
                  {pwdResult.password}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="提示">用户首次登录将被强制修改密码</Descriptions.Item>
            </Descriptions>
          </>
        )}
      </Modal>

      <Modal
        title="新建部门"
        open={deptModal}
        onCancel={() => setDeptModal(false)}
        onOk={submitDept}
        okText="创建"
        destroyOnClose
      >
        <Form form={deptForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="部门名称" rules={[{ required: true, message: '请输入部门名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="code" label="部门编码">
            <Input maxLength={32} placeholder="可留空" />
          </Form.Item>
          <Form.Item name="parent_id" label="上级部门">
            <Select
              allowClear
              placeholder="无（作为一级部门）"
              options={depts.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

export default Users
