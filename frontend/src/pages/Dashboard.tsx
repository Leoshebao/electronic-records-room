import React, { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Typography, Spin, Empty, Progress, Space } from 'antd'
import { FileTextOutlined, SwapOutlined, DatabaseOutlined, ScanOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { http, normalizeError } from '../api/client'
import { formatBytes, SECRECY_COLORS, SECRECY_LABELS, type SecrecyLevel, type StatsOverview } from '../api/types'

const TrendBars: React.FC<{ data: Array<Record<string, any>> }> = ({ data }) => {
  const max = Math.max(1, ...data.map((d) => Number(d.created || 0) + Number(d.downloads || 0)))
  return (
    <div className="trend-bars">
      {data.map((d) => {
        const created = Number(d.created || 0)
        const downloads = Number(d.downloads || 0)
        return (
          <div className="trend-bar" key={String(d.date)} title={`${d.date} 新增 ${created} / 下载 ${downloads}`}>
            <div className="trend-col">
              <div
                className="trend-seg created"
                style={{ height: `${(created / max) * 100}%` }}
              />
              <div
                className="trend-seg downloads"
                style={{ height: `${(downloads / max) * 100}%` }}
              />
            </div>
            <span className="trend-label">{String(d.date).slice(5)}</span>
          </div>
        )
      })}
    </div>
  )
}

const Dashboard: React.FC = () => {
  const [data, setData] = useState<StatsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const resp = await http.get<StatsOverview>('/stats/overview', { params: { days: 14 } })
        if (alive) setData(resp.data)
      } catch (e) {
        if (alive) setError(normalizeError(e).message)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <Spin style={{ display: 'block', margin: '120px auto' }} />
  if (error) return <Card><Typography.Text type="danger">{error}</Typography.Text></Card>
  if (!data) return <Empty />

  const docs = data.documents || {}
  const storage = data.storage || {}
  const borrow = data.borrow || {}
  const ocr = data.ocr || {}
  const users = data.users || {}

  const levelEntries = Object.entries((docs.by_level || {}) as Record<string, number>)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card hoverable onClick={() => navigate('/documents')}>
            <Statistic title="在库资料" value={docs.total || 0} prefix={<FileTextOutlined />} suffix="份" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              版本 {docs.versions || 0} · 页数 {docs.pages || 0}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card hoverable onClick={() => navigate('/borrow')}>
            <Statistic
              title="借阅（待审批）"
              value={borrow.approved || 0}
              prefix={<SwapOutlined />}
              suffix={
                <span style={{ fontSize: 13 }}>
                  <Tag color="gold" style={{ marginLeft: 4 }}>待批 {borrow.pending || 0}</Tag>
                  {borrow.overdue > 0 && <Tag color="red">逾期 {borrow.overdue}</Tag>}
                </span>
              }
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="存储占用"
              value={Number(storage.total_mb || 0).toFixed(1)}
              suffix="MB"
              prefix={<DatabaseOutlined />}
            />
            <Progress
              percent={Math.min(
                100,
                Number(storage.disk_total_gb || 0) > 0
                  ? Math.round(
                      ((Number(storage.disk_total_gb) - Number(storage.disk_free_gb || 0)) /
                        Number(storage.disk_total_gb)) *
                        100,
                    )
                  : 0,
              )}
              size="small"
              format={(p) => `盘 ${p}%`}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="解析完成" value={ocr.ready || 0} prefix={<ScanOutlined />} suffix="个文件" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              排队 {ocr.queued || 0} · 处理中 {ocr.processing || 0} · 失败 {ocr.failed || 0}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={15}>
          <Card title="近 14 天动态" extra={<Typography.Text type="secondary">新增资料 / 下载</Typography.Text>}>
            {data.trend?.length ? <TrendBars data={data.trend} /> : <Empty description="暂无数据" />}
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card title="密级分布">
            {levelEntries.length === 0 ? (
              <Empty description="暂无数据" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {levelEntries.map(([level, count]) => {
                  const total = Number(docs.total || 0) || 1
                  return (
                    <div key={level}>
                      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                        <Tag color={SECRECY_COLORS[level as SecrecyLevel] || 'default'}>
                          {SECRECY_LABELS[level as SecrecyLevel] || level}
                        </Tag>
                        <span>{count} 份</span>
                      </Space>
                      <Progress
                        percent={Math.round((Number(count) / total) * 100)}
                        showInfo={false}
                        size="small"
                      />
                    </div>
                  )
                })}
                <Typography.Text type="secondary">
                  在用账号 {users.active_total || 0} 个（<TeamOutlined />）
                </Typography.Text>
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="热门资料">
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={data.top_documents || []}
          columns={[
            { title: '档号', dataIndex: 'doc_no', width: 160 },
            {
              title: '题名',
              dataIndex: 'title',
              ellipsis: true,
              render: (_v, r: any) => (
                <a onClick={() => navigate(`/documents?doc=${r.id}`)}>{r.title}</a>
              ),
            },
            {
              title: '密级',
              dataIndex: 'secrecy_level',
              width: 90,
              render: (v: SecrecyLevel) => (
                <Tag color={SECRECY_COLORS[v] || 'default'}>{SECRECY_LABELS[v] || v}</Tag>
              ),
            },
            { title: '浏览', dataIndex: 'views', width: 80 },
            { title: '下载', dataIndex: 'downloads', width: 80 },
          ]}
          locale={{ emptyText: '暂无数据' }}
        />
      </Card>

      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        存储根目录：{storage.storage_root || '-'} · 已用 {formatBytes(storage.total_bytes)}
      </Typography.Text>
    </Space>
  )
}

export default Dashboard
