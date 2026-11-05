import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Card, Col, DatePicker, Input, Row, Select, Space, Statistic, Table, Tag, Typography, Button, message, Drawer, Descriptions,
} from 'antd'
import { ReloadOutlined, SafetyCertificateOutlined, EyeOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import { http, normalizeError } from '../api/client'
import type { AuditActionItem, AuditLog, AuditPage, AuditSummary } from '../api/types'

const RESULT_COLOR: Record<string, string> = { success: 'green', failed: 'red', denied: 'volcano' }
const RESULT_LABEL: Record<string, string> = { success: '成功', failed: '失败', denied: '拒绝' }

const fmt = (v?: string | null) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-')

const Audit: React.FC = () => {
  const [msgApi, holder] = message.useMessage()
  const [rows, setRows] = useState<AuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [loading, setLoading] = useState(false)

  const [actions, setActions] = useState<AuditActionItem[]>([])
  const [summary, setSummary] = useState<AuditSummary | null>(null)
  const [action, setAction] = useState<string | undefined>()
  const [username, setUsername] = useState('')
  const [keyword, setKeyword] = useState('')
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [detail, setDetail] = useState<AuditLog | null>(null)

  const actionLabel = useMemo(() => {
    const m = new Map(actions.map((a) => [a.action, a.label]))
    return (v: string) => m.get(v) || v
  }, [actions])

  const loadLogs = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<AuditPage>('/audit/logs', {
        params: {
          action,
          username: username || undefined,
          keyword: keyword || undefined,
          start: range?.[0]?.startOf('day').toISOString(),
          end: range?.[1]?.endOf('day').toISOString(),
          page,
          size,
        },
      })
      setRows(data.items)
      setTotal(data.total)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [action, username, keyword, range, page, size, msgApi])

  const loadMeta = useCallback(async () => {
    try {
      const [a, s] = await Promise.all([
        http.get<AuditActionItem[]>('/audit/actions'),
        http.get<AuditSummary>('/audit/summary', { params: { days: 7 } }),
      ])
      setActions(a.data)
      setSummary(s.data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    }
  }, [msgApi])

  useEffect(() => {
    void loadLogs()
  }, [loadLogs])

  useEffect(() => {
    void loadMeta()
  }, [loadMeta])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Row gutter={12}>
        <Col xs={8} md={6}>
          <Card size="small">
            <Statistic title="日志总数" value={summary?.total ?? 0} prefix={<SafetyCertificateOutlined />} />
          </Card>
        </Col>
        <Col xs={8} md={6}>
          <Card size="small">
            <Statistic title="今日新增" value={summary?.today ?? 0} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col xs={8} md={6}>
          <Card size="small">
            <Statistic
              title="失败 / 拒绝"
              value={summary?.failed ?? 0}
              valueStyle={{ color: summary?.failed ? '#cf1322' : undefined }}
            />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card size="small" title="近 7 天高频动作" bodyStyle={{ paddingTop: 8 }}>
            <Space size={[4, 4]} wrap>
              {(summary?.by_action ?? []).slice(0, 6).map((a) => (
                <Tag key={a.action} color="blue">
                  {a.label} {a.count}
                </Tag>
              ))}
              {!summary?.by_action?.length && <Typography.Text type="secondary">暂无数据</Typography.Text>}
            </Space>
          </Card>
        </Col>
      </Row>

      <Card size="small">
        <Space wrap style={{ marginBottom: 8 }}>
          <Select
            allowClear
            showSearch
            placeholder="动作类型"
            style={{ width: 200 }}
            value={action}
            onChange={(v) => {
              setAction(v)
              setPage(1)
            }}
            optionFilterProp="label"
            options={actions.map((a) => ({ value: a.action, label: `${a.label}（${a.count}）` }))}
          />
          <Input
            allowClear
            placeholder="操作人登录名"
            style={{ width: 160 }}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onPressEnter={() => {
              setPage(1)
              void loadLogs()
            }}
          />
          <Input
            allowClear
            placeholder="关键字（对象/详情）"
            style={{ width: 200 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => {
              setPage(1)
              void loadLogs()
            }}
          />
          <DatePicker.RangePicker
            value={range as any}
            onChange={(v) => {
              setRange(v as any)
              setPage(1)
            }}
            placeholder={['开始日期', '结束日期']}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void loadLogs()}>
            查询
          </Button>
          <Button
            type="text"
            onClick={() => {
              setAction(undefined)
              setUsername('')
              setKeyword('')
              setRange(null)
              setPage(1)
            }}
          >
            清空条件
          </Button>
        </Space>

        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={rows}
          scroll={{ x: 1000 }}
          pagination={{
            current: page,
            pageSize: size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, s) => {
              setPage(p)
              setSize(s)
            },
          }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 160, render: fmt },
            {
              title: '操作人',
              dataIndex: 'username',
              width: 120,
              render: (v) => v || '—',
            },
            {
              title: '动作',
              dataIndex: 'action',
              width: 150,
              render: (v: string) => <Tag color="blue">{actionLabel(v)}</Tag>,
            },
            {
              title: '对象',
              width: 160,
              render: (_v, r) =>
                r.target_type ? (
                  <Typography.Text>
                    {r.target_type}
                    {r.target_id != null ? `#${r.target_id}` : ''}
                  </Typography.Text>
                ) : (
                  '—'
                ),
            },
            { title: 'IP', dataIndex: 'ip_address', width: 130, render: (v) => v || '—' },
            {
              title: '结果',
              dataIndex: 'result',
              width: 90,
              render: (v: string) => <Tag color={RESULT_COLOR[v] || 'default'}>{RESULT_LABEL[v] || v}</Tag>,
            },
            {
              title: '详情',
              width: 80,
              fixed: 'right',
              render: (_v, r) => (
                <Button size="small" type="link" icon={<EyeOutlined />} disabled={!r.detail} onClick={() => setDetail(r)} />
              ),
            },
          ]}
        />
      </Card>

      <Drawer title="审计详情" width={520} open={!!detail} onClose={() => setDetail(null)}>
        {detail && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="时间">{fmt(detail.created_at)}</Descriptions.Item>
            <Descriptions.Item label="操作人">{detail.username || '—'}</Descriptions.Item>
            <Descriptions.Item label="动作">{actionLabel(detail.action)}</Descriptions.Item>
            <Descriptions.Item label="对象">
              {detail.target_type ? `${detail.target_type}#${detail.target_id ?? ''}` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="结果">{RESULT_LABEL[detail.result] || detail.result}</Descriptions.Item>
            <Descriptions.Item label="IP">{detail.ip_address || '—'}</Descriptions.Item>
            <Descriptions.Item label="User-Agent">
              <Typography.Text style={{ fontSize: 12, wordBreak: 'break-all' }}>{detail.user_agent || '—'}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="detail">
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(detail.detail ?? {}, null, 2)}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </Space>
  )
}

export default Audit
