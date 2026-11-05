import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Row, Space, Statistic, Table, Tag, Typography, message, Spin,
} from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { http, normalizeError } from '../api/client'
import { OCR_STATUS_LABELS, formatBytes, type OcrTask } from '../api/types'

type Any = Record<string, any>

const SystemCheck: React.FC = () => {
  const [msgApi, holder] = message.useMessage()
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState<Any | null>(null)
  const [db, setDb] = useState<Any | null>(null)
  const [storage, setStorage] = useState<Any | null>(null)
  const [engine, setEngine] = useState<Any | null>(null)
  const [tasks, setTasks] = useState<OcrTask[]>([])
  const [searchStats, setSearchStats] = useState<Any | null>(null)
  const [draining, setDraining] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const results = await Promise.allSettled([
      http.get<Any>('/health'),
      http.get<Any>('/health/db'),
      http.get<Any>('/health/storage'),
      http.get<Any>('/ocr/engine'),
      http.get<Any>('/ocr/tasks', { params: { size: 10 } }),
      http.get<Any>('/search/stats'),
    ])
    const val = <T,>(i: number): T | null =>
      results[i].status === 'fulfilled' ? ((results[i] as PromiseFulfilledResult<any>).value.data as T) : null
    setHealth(val<Any>(0))
    setDb(val<Any>(1))
    setStorage(val<Any>(2))
    setEngine(val<Any>(3))
    const t = val<Any>(4)
    setTasks((t?.items ?? t ?? []) as OcrTask[])
    setSearchStats(val<Any>(5))
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed) msgApi.warning(`${failed} 项检查请求失败，可能是权限不足或服务未就绪`)
    setLoading(false)
  }, [msgApi])

  useEffect(() => {
    void load()
  }, [load])

  const drain = async () => {
    setDraining(true)
    try {
      const { data } = await http.post<Any>('/ocr/drain', null, { params: { limit: 20 } })
      msgApi.success(`已处理队列：${JSON.stringify(data)}`)
      await load()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setDraining(false)
    }
  }

  const stateTag = (ok: boolean, okText = '正常', badText = '异常') =>
    ok ? <Tag color="green" icon={<CheckCircleOutlined />}>{okText}</Tag> : <Tag color="red" icon={<CloseCircleOutlined />}>{badText}</Tag>

  if (loading && !health) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Row gutter={12}>
        <Col xs={24} lg={12}>
          <Card
            size="small"
            title="服务与数据库"
            extra={
              <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
                重新检测
              </Button>
            }
          >
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="后端服务">
                {stateTag(!!health)} {health?.app} · {health?.env}
              </Descriptions.Item>
              <Descriptions.Item label="服务器时间">{health?.time || '-'}</Descriptions.Item>
              <Descriptions.Item label="数据库">
                {stateTag(db?.status === 'ok', `已连接 ${db?.pg_version || ''}`, db?.detail || '未就绪')}
              </Descriptions.Item>
              <Descriptions.Item label="pgvector / 全文检索">
                <Space size={4}>
                  {stateTag(!!db?.pgvector, 'pgvector 就绪', '未检测')}
                  {stateTag(!!db?.trgm, 'pg_trgm 就绪', '未检测')}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="存储与磁盘">
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="存储根目录">
                <Typography.Text style={{ fontSize: 12, wordBreak: 'break-all' }}>{storage?.root || storage?.storage_root || '-'}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态">{stateTag(storage?.status === 'ok' || !!storage?.writable, '可写', storage?.detail || '未就绪')}</Descriptions.Item>
              <Descriptions.Item label="已用 / 可用">
                {storage?.used_bytes != null ? `${formatBytes(storage.used_bytes)} / ${formatBytes(storage.free_bytes)}` : storage?.used || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="文件数">{storage?.file_count ?? storage?.files ?? '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col xs={24} lg={12}>
          <Card size="small" title="OCR / 解析引擎">
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="引擎">
                {stateTag(!!engine?.available, engine?.name || engine?.engine || '就绪', engine?.detail || '不可用')}
              </Descriptions.Item>
              <Descriptions.Item label="版本 / 语言">{engine?.version || engine?.lang || '-'}</Descriptions.Item>
              <Descriptions.Item label="队列">
                <Space size={4} wrap>
                  <Tag color="gold">排队 {engine?.queued ?? 0}</Tag>
                  <Tag color="blue">处理中 {engine?.processing ?? 0}</Tag>
                  <Tag color="green">完成 {engine?.ready ?? 0}</Tag>
                  <Tag color="red">失败 {engine?.failed ?? 0}</Tag>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="操作">
                <Button size="small" icon={<ThunderboltOutlined />} loading={draining} onClick={drain}>
                  立即处理队列
                </Button>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="检索能力">
            <Space size={24} wrap>
              <Statistic title="已建索引文档" value={searchStats?.indexed ?? searchStats?.documents ?? '-'} />
              <Statistic title="词条数" value={searchStats?.terms ?? '-'} />
              <Statistic title="平均耗时" value={searchStats?.avg_ms ?? '-'} suffix="ms" />
            </Space>
            <Descriptions column={1} bordered size="small" style={{ marginTop: 12 }}>
              <Descriptions.Item label="全文检索 (FTS)">{stateTag(!!searchStats?.fts, '可用', '不可用')}</Descriptions.Item>
              <Descriptions.Item label="模糊检索 (trgm)">{stateTag(!!searchStats?.trgm, '可用', '不可用')}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="最近 OCR 任务"
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        }
      >
        {tasks.length === 0 ? (
          <Alert type="success" showIcon message="队列为空，所有文件均已解析完成" />
        ) : (
          <Table
            rowKey="id"
            size="small"
            dataSource={tasks}
            pagination={false}
            columns={[
              { title: '任务', dataIndex: 'id', width: 70 },
              { title: '文件', dataIndex: 'file_id', width: 80, render: (v) => `#${v}` },
              { title: '文档', dataIndex: 'document_id', width: 80, render: (v) => (v ? `#${v}` : '-') },
              {
                title: '状态',
                dataIndex: 'status',
                width: 100,
                render: (v: keyof typeof OCR_STATUS_LABELS) => (
                  <Tag color={v === 'ready' ? 'green' : v === 'failed' ? 'red' : v === 'processing' ? 'blue' : 'gold'}>
                    {OCR_STATUS_LABELS[v] || v}
                  </Tag>
                ),
              },
              { title: '引擎', dataIndex: 'engine', width: 110, render: (v) => v || '-' },
              { title: '重试', dataIndex: 'retry_count', width: 70, align: 'center' },
              { title: '错误', dataIndex: 'error_msg', ellipsis: true, render: (v) => v || '-' },
            ]}
          />
        )}
      </Card>
    </Space>
  )
}

export default SystemCheck
