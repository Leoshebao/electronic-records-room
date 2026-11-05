import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, InputNumber, Row, Select, Space, Statistic, Table, Tag, Typography, message, Popconfirm,
} from 'antd'
import { CloudDownloadOutlined, CloudServerOutlined, DeleteOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { downloadFile, http, normalizeError } from '../api/client'
import { formatBytes, type BackupList, type BackupOut } from '../api/types'

const TYPE_LABEL: Record<string, string> = { full: '全量', db: '数据库', files: '文件' }
const fmt = (v?: string | null) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-')

const Backups: React.FC = () => {
  const [msgApi, holder] = message.useMessage()
  const [data, setData] = useState<BackupList | null>(null)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [backupType, setBackupType] = useState('full')
  const [keepDays, setKeepDays] = useState<number | null>(null)
  const [cleaning, setCleaning] = useState(false)
  const [downloading, setDownloading] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data: d } = await http.get<BackupList>('/backups', { params: { limit: 100 } })
      setData(d)
      if (keepDays == null) setKeepDays(d.keep_days)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [keepDays, msgApi])

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runBackup = async () => {
    setRunning(true)
    try {
      const { data: rec } = await http.post<BackupOut>('/backups', null, { params: { backup_type: backupType } })
      msgApi.success(`备份完成：${rec.filename}（${formatBytes(rec.size_bytes)}）`)
      await load()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setRunning(false)
    }
  }

  const cleanup = async () => {
    setCleaning(true)
    try {
      const { data: r } = await http.delete<Record<string, unknown>>('/backups/cleanup', {
        params: { keep_days: keepDays ?? undefined },
      })
      msgApi.success(`清理完成：${JSON.stringify(r)}`)
      await load()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setCleaning(false)
    }
  }

  const items = data?.items ?? []
  const lastOk = items.find((i) => i.status === 'success')

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Row gutter={12}>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic title="备份记录数" value={data?.total ?? 0} prefix={<CloudServerOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic title="最近成功备份" value={lastOk ? fmt(lastOk.created_at) : '暂无'} />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small">
            <Statistic
              title="保留天数 / 备份目录"
              value={data?.keep_days ?? '-'}
              suffix="天"
              valueStyle={{ fontSize: 20 }}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>
              {data?.backup_root || '-'}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Card size="small" title="执行备份">
        <Space wrap>
          <Select
            value={backupType}
            onChange={setBackupType}
            style={{ width: 180 }}
            options={[
              { value: 'full', label: '全量备份（库 + 文件）' },
              { value: 'db', label: '仅数据库' },
              { value: 'files', label: '仅文件目录' },
            ]}
          />
          <Button type="primary" icon={<ThunderboltOutlined />} loading={running} onClick={runBackup}>
            {running ? '备份中，请稍候…' : '立即备份'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新记录
          </Button>
          <Space size={4}>
            <Typography.Text type="secondary">保留</Typography.Text>
            <InputNumber min={1} max={3650} value={keepDays} onChange={setKeepDays} style={{ width: 90 }} />
            <Typography.Text type="secondary">天</Typography.Text>
            <Popconfirm
              title="清理过期备份？"
              description="将物理删除超过保留天数的备份包，不可恢复"
              okButtonProps={{ danger: true }}
              onConfirm={cleanup}
            >
              <Button danger icon={<DeleteOutlined />} loading={cleaning}>
                清理过期
              </Button>
            </Popconfirm>
          </Space>
        </Space>
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          message="备份文件存放于服务器本地目录，建议定期将备份包复制到异地存储（如移动硬盘 / NAS）"
        />
      </Card>

      <Card size="small" title="备份记录">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={items}
          scroll={{ x: 900 }}
          pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
          columns={[
            { title: '文件名', dataIndex: 'filename', ellipsis: true },
            {
              title: '类型',
              dataIndex: 'backup_type',
              width: 90,
              render: (v: string) => <Tag>{TYPE_LABEL[v] || v}</Tag>,
            },
            { title: '大小', dataIndex: 'size_bytes', width: 100, render: (v: number) => formatBytes(v) },
            {
              title: '状态',
              dataIndex: 'status',
              width: 110,
              render: (v: string, r) =>
                v === 'success' ? (
                  <Tag color="green">成功</Tag>
                ) : (
                  <Tag color="red" title={r.error_msg || ''}>
                    失败
                  </Tag>
                ),
            },
            { title: '开始', dataIndex: 'started_at', width: 160, render: fmt },
            { title: '完成', dataIndex: 'finished_at', width: 160, render: fmt },
            {
              title: '操作',
              width: 100,
              fixed: 'right',
              render: (_v, r) => (
                <Button
                  size="small"
                  type="link"
                  icon={<CloudDownloadOutlined />}
                  disabled={r.status !== 'success'}
                  loading={downloading === r.id}
                  onClick={async () => {
                    setDownloading(r.id)
                    try {
                      await downloadFile(`/backups/${r.id}/download`, r.filename)
                    } catch (e) {
                      msgApi.error(normalizeError(e).message)
                    } finally {
                      setDownloading(null)
                    }
                  }}
                >
                  下载
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}

export default Backups
