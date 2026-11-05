import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Descriptions, Form, Input, InputNumber, Modal, Popconfirm, Space, Table, Tabs, Tag,
  Typography, message, Badge, Alert, Switch,
} from 'antd'
import { ReloadOutlined, CheckOutlined, CloseOutlined, RollbackOutlined } from '@ant-design/icons'
import { http, normalizeError } from '../api/client'
import {
  BORROW_STATUS_COLORS, BORROW_STATUS_LABELS, SECRECY_COLORS, SECRECY_LABELS,
  type BorrowPage, type BorrowRequest, type BorrowStatus, type SecrecyLevel,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'

const StatusTag: React.FC<{ status: BorrowStatus }> = ({ status }) => (
  <Tag color={BORROW_STATUS_COLORS[status] || 'default'}>{BORROW_STATUS_LABELS[status] || status}</Tag>
)

const fmt = (v?: string | null) => (v ? String(v).replace('T', ' ').slice(0, 16) : '-')

const Borrow: React.FC = () => {
  const { has, user } = useAuth()
  const [msgApi, holder] = message.useMessage()
  const [tab, setTab] = useState('mine')

  const [mineData, setMineData] = useState<BorrowPage | null>(null)
  const [pendingData, setPendingData] = useState<BorrowPage | null>(null)
  const [allData, setAllData] = useState<BorrowPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<BorrowRequest | null>(null)
  const [rejecting, setRejecting] = useState<BorrowRequest | null>(null)
  const [approving, setApproving] = useState<BorrowRequest | null>(null)
  const [sweeper, setSweeper] = useState<any>(null)

  const loadMine = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<BorrowPage>('/borrow/mine', { params: { page: 1, size: 50 } })
      setMineData(data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [msgApi])

  const loadPending = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<BorrowPage>('/borrow/pending', { params: { page: 1, size: 50 } })
      setPendingData(data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [msgApi])

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<BorrowPage>('/borrow/requests', {
        params: { mine: false, page: 1, size: 50 },
      })
      setAllData(data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [msgApi])

  const loadSweeper = useCallback(async () => {
    try {
      const { data } = await http.get('/borrow/sweeper')
      setSweeper(data)
    } catch {
      setSweeper(null)
    }
  }, [])

  useEffect(() => {
    if (tab === 'mine') void loadMine()
    if (tab === 'pending') void loadPending()
    if (tab === 'all') void loadAll()
    if (tab === 'sweeper') void loadSweeper()
  }, [tab, loadMine, loadPending, loadAll, loadSweeper])

  const act = async (req: BorrowRequest, action: 'cancel' | 'return' | 'renew', extra?: any) => {
    try {
      await http.post(`/borrow/requests/${req.id}/${action}`, extra || {})
      msgApi.success('操作成功')
      void loadMine()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    }
  }

  const baseColumns = (showApplicant = false) => [
    { title: '申请单号', dataIndex: 'request_no', width: 170 },
    {
      title: '资料',
      render: (_: any, r: BorrowRequest) => (
        <Space direction="vertical" size={0}>
          <span>{r.title || `#${r.document_id}`}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.doc_no}
          </Typography.Text>
        </Space>
      ),
    },
    ...(showApplicant
      ? [{ title: '申请人', dataIndex: 'applicant_name', width: 100 }]
      : []),
    {
      title: '密级',
      dataIndex: 'secrecy_level',
      width: 86,
      render: (v: SecrecyLevel) =>
        v ? <Tag color={SECRECY_COLORS[v]}>{SECRECY_LABELS[v]}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 96,
      render: (v: BorrowStatus) => <StatusTag status={v} />,
    },
    { title: '天数', dataIndex: 'requested_days', width: 64, align: 'center' as const },
    {
      title: '剩余',
      dataIndex: 'remaining_days',
      width: 70,
      align: 'center' as const,
      render: (v: number, r: BorrowRequest) =>
        r.status === 'approved' ? (v > 0 ? `${v} 天` : <Tag color="red">已逾期</Tag>) : '-',
    },
    { title: '申请时间', dataIndex: 'created_at', width: 150, render: fmt },
    {
      title: '操作',
      width: 210,
      render: (_: any, r: BorrowRequest) => (
        <Space size={4} wrap>
          <Button size="small" type="link" onClick={() => setDetail(r)}>
            详情
          </Button>
          {r.status === 'pending' && r.applicant_id === user?.id && (
            <Popconfirm title="确认撤回该申请？" onConfirm={() => act(r, 'cancel')}>
              <Button size="small" type="link" danger>
                撤回
              </Button>
            </Popconfirm>
          )}
          {r.status === 'approved' && (
            <>
              <Popconfirm title="确认归还？" onConfirm={() => act(r, 'return')}>
                <Button size="small" type="link" icon={<RollbackOutlined />}>
                  归还
                </Button>
              </Popconfirm>
              <Popconfirm
                title="申请续借 7 天？"
                onConfirm={() => act(r, 'renew', { days: 7 })}
                disabled={r.renew_count >= 1}
              >
                <Button size="small" type="link" disabled={r.renew_count >= 1}>
                  续借
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ]

  const approvalColumns = [
    ...baseColumns(true),
    {
      title: '审批',
      width: 130,
      fixed: 'right' as const,
      render: (_: any, r: BorrowRequest) => (
        <Space size={4}>
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => setApproving(r)}>
            通过
          </Button>
          <Button size="small" danger icon={<CloseOutlined />} onClick={() => setRejecting(r)}>
            驳回
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Card size="small" bodyStyle={{ paddingBottom: 0 }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'mine',
              label: <Badge count={0} offset={[10, 0]}>我的借阅</Badge>,
              children: (
                <>
                  <Space style={{ marginBottom: 8 }}>
                    <Button icon={<ReloadOutlined />} size="small" onClick={() => void loadMine()}>
                      刷新
                    </Button>
                    <Typography.Text type="secondary">借阅中的资料可在线观看，下载/打印需审批时授予</Typography.Text>
                  </Space>
                  <Table
                    rowKey="id"
                    size="small"
                    loading={loading}
                    dataSource={mineData?.items || []}
                    columns={baseColumns() as any}
                    scroll={{ x: 1100 }}
                    pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                  />
                </>
              ),
            },
            ...(has('borrow:approve')
              ? [
                  {
                    key: 'pending',
                    label: `待审批${pendingData?.total ? `（${pendingData.total}）` : ''}`,
                    children: (
                      <Table
                        rowKey="id"
                        size="small"
                        loading={loading}
                        dataSource={pendingData?.items || []}
                        columns={approvalColumns as any}
                        scroll={{ x: 1250 }}
                        pagination={{ pageSize: 20 }}
                        locale={{ emptyText: '暂无待审批申请' }}
                      />
                    ),
                  },
                  {
                    key: 'all',
                    label: '全部申请',
                    children: (
                      <Table
                        rowKey="id"
                        size="small"
                        loading={loading}
                        dataSource={allData?.items || []}
                        columns={baseColumns(true) as any}
                        scroll={{ x: 1200 }}
                        pagination={{ pageSize: 20 }}
                      />
                    ),
                  },
                  {
                    key: 'sweeper',
                    label: '到期回收',
                    children: (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Alert
                          type="info"
                          showIcon
                          message="系统内置到期回收线程，会定时把超期未归还的借阅置为已到期并收回下载/打印权限。"
                        />
                        <Descriptions bordered size="small" column={2}>
                          <Descriptions.Item label="线程启用">{sweeper?.enabled ? '是' : '否'}</Descriptions.Item>
                          <Descriptions.Item label="运行中">{sweeper?.alive ? '是' : '否'}</Descriptions.Item>
                          <Descriptions.Item label="扫描间隔">{sweeper?.interval || '-'} 秒</Descriptions.Item>
                          <Descriptions.Item label="上次执行">{sweeper?.last_run || '-'}</Descriptions.Item>
                          <Descriptions.Item label="上次结果" span={2}>
                            {sweeper?.last_result ? JSON.stringify(sweeper.last_result) : '-'}
                          </Descriptions.Item>
                        </Descriptions>
                        <Space>
                          <Button
                            type="primary"
                            onClick={async () => {
                              try {
                                const { data } = await http.post('/borrow/sweep')
                                msgApi.success(`已回收 ${data.expired} 条，撤销权限 ${data.purged_permissions} 项`)
                                void loadSweeper()
                              } catch (e) {
                                msgApi.error(normalizeError(e).message)
                              }
                            }}
                          >
                            立即执行回收
                          </Button>
                          <Button icon={<ReloadOutlined />} onClick={() => void loadSweeper()}>
                            刷新状态
                          </Button>
                        </Space>
                      </Space>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Card>

      <Modal
        title="借阅详情"
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        width={640}
      >
        {detail && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="申请单号">{detail.request_no}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <StatusTag status={detail.status} />
            </Descriptions.Item>
            <Descriptions.Item label="资料" span={2}>
              {detail.doc_no} - {detail.title}
            </Descriptions.Item>
            <Descriptions.Item label="申请人">{detail.applicant_name}</Descriptions.Item>
            <Descriptions.Item label="申请天数">{detail.requested_days} 天</Descriptions.Item>
            <Descriptions.Item label="下载权">{detail.want_download ? '是' : '否'}</Descriptions.Item>
            <Descriptions.Item label="打印权">{detail.want_print ? '是' : '否'}</Descriptions.Item>
            <Descriptions.Item label="借阅开始">{fmt(detail.start_at)}</Descriptions.Item>
            <Descriptions.Item label="应还时间">{fmt(detail.due_at)}</Descriptions.Item>
            <Descriptions.Item label="归还时间">{fmt(detail.returned_at)}</Descriptions.Item>
            <Descriptions.Item label="续借次数">{detail.renew_count}</Descriptions.Item>
            <Descriptions.Item label="借阅事由" span={2}>
              {detail.reason}
            </Descriptions.Item>
            {detail.reject_reason && (
              <Descriptions.Item label="驳回原因" span={2}>
                {detail.reject_reason}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>

      <ApproveModal
        req={approving}
        onClose={() => setApproving(null)}
        onDone={() => {
          setApproving(null)
          void loadPending()
        }}
      />
      <RejectModal
        req={rejecting}
        onClose={() => setRejecting(null)}
        onDone={() => {
          setRejecting(null)
          void loadPending()
        }}
      />
    </Space>
  )
}

const ApproveModal: React.FC<{ req: BorrowRequest | null; onClose: () => void; onDone: () => void }> = ({
  req,
  onClose,
  onDone,
}) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()
  if (!req) return null

  const submit = async () => {
    try {
      const v = await form.validateFields()
      setLoading(true)
      await http.post(`/borrow/requests/${req.id}/approve`, {
        days: v.days,
        can_download: v.can_download,
        can_print: v.can_print,
      })
      msgApi.success('已通过')
      onDone()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title={`审批通过 - ${req.request_no}`} open onCancel={onClose} onOk={submit} confirmLoading={loading} okText="确认通过">
      {holder}
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ days: req.requested_days, can_download: req.want_download, can_print: req.want_print }}
      >
        <Form.Item label="借阅事由">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            {req.reason}
          </Typography.Paragraph>
        </Form.Item>
        <Form.Item name="days" label="批准天数" rules={[{ required: true }]}>
          <InputNumber min={1} max={90} style={{ width: '100%' }} addonAfter="天" />
        </Form.Item>
        <Form.Item name="can_download" label="授予下载权" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="can_print" label="授予打印权" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

const RejectModal: React.FC<{ req: BorrowRequest | null; onClose: () => void; onDone: () => void }> = ({
  req,
  onClose,
  onDone,
}) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()
  if (!req) return null

  const submit = async () => {
    try {
      const v = await form.validateFields()
      setLoading(true)
      await http.post(`/borrow/requests/${req.id}/reject`, { reason: v.reason })
      msgApi.success('已驳回')
      onDone()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title={`驳回申请 - ${req.request_no}`} open onCancel={onClose} onOk={submit} confirmLoading={loading} okText="确认驳回" okButtonProps={{ danger: true }}>
      {holder}
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="reason"
          label="驳回原因"
          rules={[{ required: true, message: '请填写驳回原因' }, { min: 2, message: '至少 2 个字' }]}
        >
          <Input.TextArea rows={3} maxLength={1000} showCount />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default Borrow
