import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button, Card, Col, Descriptions, Drawer, Empty, Form, Input, InputNumber, Modal, Popconfirm,
  Row, Select, Space, Table, Tag, Tooltip, TreeSelect, Typography, Upload, message, Divider, Badge,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  UploadOutlined, ReloadOutlined, DownloadOutlined, EyeOutlined, EditOutlined,
  DeleteOutlined, SwapOutlined, HistoryOutlined, PlusOutlined, FileOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { downloadFile, http, normalizeError, openBlobInNewTab } from '../api/client'
import {
  DOC_STATUS_LABELS, formatBytes, OCR_STATUS_LABELS, SECRECY_COLORS, SECRECY_LABELS,
  type Category, type DocumentBrief, type DocumentDetail, type DocumentPage, type Room, type SecrecyLevel,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'

const SECRECY_OPTIONS = (Object.keys(SECRECY_LABELS) as SecrecyLevel[]).map((v) => ({
  value: v,
  label: SECRECY_LABELS[v],
}))

const flattenCategoryTree = (nodes: Category[]): Array<{ title: string; value: number; children?: any[] }> =>
  nodes.map((n) => ({
    title: n.name,
    value: n.id,
    children: n.children?.length ? flattenCategoryTree(n.children) : undefined,
  }))

const Documents: React.FC = () => {
  const { has } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [msgApi, holder] = message.useMessage()

  const [rooms, setRooms] = useState<Room[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [roomId, setRoomId] = useState<number | undefined>()
  const [categoryId, setCategoryId] = useState<number | undefined>()
  const [keyword, setKeyword] = useState('')
  const [level, setLevel] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [year, setYear] = useState<number | undefined>()
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [sort, setSort] = useState('created_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')

  const [rows, setRows] = useState<DocumentBrief[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [detail, setDetail] = useState<DocumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [borrowDoc, setBorrowDoc] = useState<DocumentBrief | null>(null)
  const [versionOpen, setVersionOpen] = useState<DocumentDetail | null>(null)

  const loadRooms = useCallback(async () => {
    try {
      const { data } = await http.get<any>('/rooms')
      setRooms(data as Room[])
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    }
  }, [msgApi])

  const loadCategories = useCallback(async (rid?: number) => {
    try {
      const { data } = await http.get<any>('/categories/tree', { params: rid ? { room_id: rid } : {} })
      // 后端双形态：传 room_id 返回类目数组；不传返回 { rooms:[{ categories:[…] }], user }
      const list: Category[] = Array.isArray(data)
        ? data
        : (data?.rooms ?? []).flatMap((r: any) => r?.categories ?? [])
      setCategories(list)
    } catch {
      setCategories([])
    }
  }, [])

  const loadDocs = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<DocumentPage>('/documents', {
        params: {
          keyword: keyword || undefined,
          room_id: roomId,
          category_id: categoryId,
          secrecy_level: level,
          status,
          archive_year: year,
          page,
          size,
          sort,
          order,
        },
      })
      setRows(data.items)
      setTotal(data.meta.total)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [keyword, roomId, categoryId, level, status, year, page, size, sort, order, msgApi])

  useEffect(() => {
    void loadRooms()
  }, [loadRooms])

  useEffect(() => {
    void loadCategories(roomId)
    setCategoryId(undefined)
  }, [roomId, loadCategories])

  useEffect(() => {
    void loadDocs()
  }, [loadDocs])

  // 支持从概览页跳转直接打开某份资料的详情
  useEffect(() => {
    const docId = searchParams.get('doc')
    if (docId) {
      setDetailId(Number(docId))
      searchParams.delete('doc')
      setSearchParams(searchParams, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!detailId) {
      setDetail(null)
      return
    }
    setDetailLoading(true)
    http
      .get<DocumentDetail>(`/documents/${detailId}`)
      .then(({ data }) => setDetail(data))
      .catch((e) => msgApi.error(normalizeError(e).message))
      .finally(() => setDetailLoading(false))
  }, [detailId, msgApi])

  const openDetail = (id: number) => setDetailId(id)

  const [reocrLoading, setReocrLoading] = useState(false)
  // 重新解析：文件 OCR 状态置回 queued 并即时跑一次队列（服务端限 doc:edit）
  const reocr = async (docId: number) => {
    setReocrLoading(true)
    try {
      const { data } = await http.post<{ message: string }>(`/ocr/documents/${docId}/reocr`, null, {
        params: { run_now: true },
      })
      msgApi.success(data.message || '已重新提交解析')
      await reloadDetail(docId)
      void loadDocs()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setReocrLoading(false)
    }
  }


  const reloadDetail = async (id: number) => {
    try {
      const { data } = await http.get<DocumentDetail>(`/documents/${id}`)
      setDetail(data)
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    }
  }

  const doDelete = async (row: DocumentBrief) => {
    try {
      await http.delete(`/documents/${row.id}`)
      msgApi.success('已归档删除该资料')
      void loadDocs()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    }
  }

  const columns: ColumnsType<DocumentBrief> = [
    { title: '档号', dataIndex: 'doc_no', width: 170, fixed: 'left' },
    {
      title: '题名',
      dataIndex: 'title',
      ellipsis: true,
      render: (v, r) => (
        <Space direction="vertical" size={0}>
          <a onClick={() => openDetail(r.id)}>{v}</a>
          {r.keywords && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              关键词：{r.keywords}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: '资料室',
      dataIndex: 'room_id',
      width: 120,
      render: (v) => rooms.find((r) => r.id === v)?.name || v,
    },
    {
      title: '密级',
      dataIndex: 'secrecy_level',
      width: 86,
      render: (v: SecrecyLevel) => <Tag color={SECRECY_COLORS[v]}>{SECRECY_LABELS[v]}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 86,
      render: (v: keyof typeof DOC_STATUS_LABELS) => (
        <Badge status={v === 'active' ? 'success' : 'default'} text={DOC_STATUS_LABELS[v] || v} />
      ),
    },
    { title: '文件', dataIndex: 'file_count', width: 64, align: 'center' },
    { title: '页数', dataIndex: 'page_count', width: 64, align: 'center' },
    {
      title: '大小',
      dataIndex: 'total_size',
      width: 90,
      render: (v: number) => formatBytes(v),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => (v ? String(v).replace('T', ' ').slice(0, 16) : '-'),
    },
    {
      title: '操作',
      width: 200,
      fixed: 'right',
      render: (_v, r) => (
        <Space size={4}>
          <Tooltip title="查看详情">
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => openDetail(r.id)} />
          </Tooltip>
          <Tooltip title="申请借阅">
            <Button size="small" type="text" icon={<SwapOutlined />} onClick={() => setBorrowDoc(r)} />
          </Tooltip>
          {has('doc:edit') && (
            <Tooltip title="编辑元数据">
              <Button
                size="small"
                type="text"
                icon={<EditOutlined />}
                onClick={() => {
                  setDetail(detail && detail.id === r.id ? detail : null)
                  setEditTarget(r)
                  setEditOpen(true)
                }}
              />
            </Tooltip>
          )}
          {has('doc:delete') && (
            <Popconfirm
              title="确认删除该资料？"
              description="删除后进入已归档状态，仅管理员可追溯"
              okButtonProps={{ danger: true }}
              okText="删除"
              cancelText="取消"
              onConfirm={() => doDelete(r)}
            >
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const [editTarget, setEditTarget] = useState<DocumentBrief | null>(null)
  const [editForm] = Form.useForm()

  const submitEdit = async () => {
    if (!editTarget) return
    try {
      const values = await editForm.validateFields()
      await http.patch(`/documents/${editTarget.id}`, values)
      msgApi.success('已保存')
      setEditOpen(false)
      void loadDocs()
      if (detailId === editTarget.id) void reloadDetail(editTarget.id)
    } catch (e) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    }
  }

  const categoryTreeData = useMemo(() => flattenCategoryTree(categories), [categories])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Card size="small">
        <Row gutter={[8, 8]} align="middle">
          <Col xs={24} md={6}>
            <Input.Search
              placeholder="档号 / 题名 / 关键词"
              allowClear
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onSearch={() => setPage(1)}
            />
          </Col>
          <Col xs={12} md={4}>
            <Select
              allowClear
              placeholder="资料室"
              style={{ width: '100%' }}
              value={roomId}
              onChange={(v) => {
                setRoomId(v)
                setPage(1)
              }}
              options={rooms.map((r) => ({ value: r.id, label: `${r.name}（${r.code}）` }))}
            />
          </Col>
          <Col xs={12} md={4}>
            <TreeSelect
              allowClear
              placeholder="类目"
              style={{ width: '100%' }}
              value={categoryId}
              treeData={categoryTreeData}
              disabled={!roomId}
              onChange={(v) => {
                setCategoryId(v)
                setPage(1)
              }}
              treeDefaultExpandAll
            />
          </Col>
          <Col xs={12} md={3}>
            <Select
              allowClear
              placeholder="密级"
              style={{ width: '100%' }}
              value={level}
              onChange={(v) => {
                setLevel(v)
                setPage(1)
              }}
              options={SECRECY_OPTIONS}
            />
          </Col>
          <Col xs={12} md={3}>
            <Select
              allowClear
              placeholder="状态"
              style={{ width: '100%' }}
              value={status}
              onChange={(v) => {
                setStatus(v)
                setPage(1)
              }}
              options={Object.entries(DOC_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </Col>
          <Col xs={12} md={2}>
            <InputNumber
              placeholder="年度"
              style={{ width: '100%' }}
              value={year}
              min={1900}
              max={2100}
              onChange={(v) => {
                setYear(v ? Number(v) : undefined)
                setPage(1)
              }}
            />
          </Col>
          <Col xs={12} md={2}>
            <Button icon={<ReloadOutlined />} onClick={() => void loadDocs()} block>
              刷新
            </Button>
          </Col>
        </Row>
        <Row justify="space-between" align="middle" style={{ marginTop: 8 }}>
          <Space>
            <Typography.Text type="secondary">共 {total} 份资料</Typography.Text>
            <Select
              size="small"
              value={`${sort}:${order}`}
              style={{ width: 160 }}
              onChange={(v) => {
                const [s, o] = String(v).split(':')
                setSort(s)
                setOrder(o as 'asc' | 'desc')
              }}
              options={[
                { value: 'created_at:desc', label: '最新入库' },
                { value: 'created_at:asc', label: '最早入库' },
                { value: 'title:asc', label: '题名升序' },
                { value: 'doc_no:asc', label: '档号升序' },
                { value: 'archive_year:desc', label: '年度倒序' },
              ]}
            />
          </Space>
          {has('doc:upload') && (
            <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
              上传资料
            </Button>
          )}
        </Row>
      </Card>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1200 }}
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
        locale={{ emptyText: <Empty description="暂无资料" /> }}
      />

      {uploadOpen && (
        <UploadModal
          rooms={rooms}
          defaultRoomId={roomId}
          onClose={() => setUploadOpen(false)}
          onDone={() => {
            setUploadOpen(false)
            void loadDocs()
          }}
        />
      )}

      {editOpen && editTarget && (
        <Modal
          title="编辑资料元数据"
          open={editOpen}
          onCancel={() => setEditOpen(false)}
          onOk={submitEdit}
          okText="保存"
          destroyOnClose
        >
          <Form
            form={editForm}
            layout="vertical"
            preserve={false}
            initialValues={{
              title: editTarget.title,
              secrecy_level: editTarget.secrecy_level,
              status: editTarget.status,
              summary: editTarget.summary,
              keywords: editTarget.keywords,
              archive_year: editTarget.archive_year,
              retention_years: editTarget.retention_years,
              change_note: '',
            }}
          >
            <Form.Item name="title" label="题名" rules={[{ required: true, message: '请输入题名' }]}>
              <Input maxLength={500} />
            </Form.Item>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item name="secrecy_level" label="密级">
                  <Select options={SECRECY_OPTIONS} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="status" label="状态">
                  <Select options={Object.entries(DOC_STATUS_LABELS).map(([value, label]) => ({ value, label }))} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="keywords" label="关键词">
              <Input placeholder="空格或逗号分隔" />
            </Form.Item>
            <Form.Item name="summary" label="摘要">
              <Input.TextArea rows={3} />
            </Form.Item>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item name="archive_year" label="归档年度">
                  <InputNumber style={{ width: '100%' }} min={1900} max={2100} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="retention_years" label="保管期限（年）">
                  <InputNumber style={{ width: '100%' }} min={1} max={100} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="change_note" label="变更说明">
              <Input placeholder="本次修改原因（写入版本记录）" />
            </Form.Item>
          </Form>
        </Modal>
      )}

      {borrowDoc && (
        <BorrowApplyModal
          doc={borrowDoc}
          onClose={() => setBorrowDoc(null)}
          onDone={() => setBorrowDoc(null)}
        />
      )}

      <Drawer
        title={detail?.title || '资料详情'}
        width={860}
        open={!!detailId}
        onClose={() => setDetailId(null)}
        loading={detailLoading}
        extra={
          detail && (
            <Space>
              <Button icon={<SwapOutlined />} onClick={() => setBorrowDoc(detail)}>
                申请借阅
              </Button>
              {has('doc:edit') && (
                <Button
                  icon={<PlusOutlined />}
                  onClick={() => setVersionOpen(detail)}
                >
                  新增版本
                </Button>
              )}
              {has('doc:edit') && (
                <Tooltip title="文件 OCR 状态置回待解析并立即跑一次队列，用于扫描件识别失败后重试">
                  <Button
                    icon={<ReloadOutlined />}
                    loading={reocrLoading}
                    onClick={() => void reocr(detail.id)}
                  >
                    重新解析
                  </Button>
                </Tooltip>
              )}
            </Space>
          )
        }
      >
        {detail && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="档号">{detail.doc_no}</Descriptions.Item>
              <Descriptions.Item label="题名">{detail.title}</Descriptions.Item>
              <Descriptions.Item label="资料室">
                {rooms.find((r) => r.id === detail.room_id)?.name || detail.room_id}
              </Descriptions.Item>
              <Descriptions.Item label="密级">
                <Tag color={SECRECY_COLORS[detail.secrecy_level]}>
                  {SECRECY_LABELS[detail.secrecy_level]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">{DOC_STATUS_LABELS[detail.status]}</Descriptions.Item>
              <Descriptions.Item label="归档年度">{detail.archive_year || '-'}</Descriptions.Item>
              <Descriptions.Item label="保管期限">
                {detail.retention_years ? `${detail.retention_years} 年` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="浏览/下载">
                {detail.view_count} / {detail.download_count}
              </Descriptions.Item>
              <Descriptions.Item label="关键词" span={2}>
                {detail.keywords || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="摘要" span={2}>
                {detail.summary || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>
                {String(detail.created_at).replace('T', ' ').slice(0, 19)}
              </Descriptions.Item>
            </Descriptions>

            <Divider orientation="left" style={{ margin: '4px 0' }}>
              电子文件（{detail.files.length}）
            </Divider>
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={detail.files}
              columns={[
                {
                  title: '文件名',
                  dataIndex: 'original_name',
                  render: (v) => (
                    <Space>
                      <FileOutlined />
                      <span>{v}</span>
                    </Space>
                  ),
                },
                { title: '大小', dataIndex: 'size_bytes', width: 90, render: (v) => formatBytes(v) },
                { title: '页数', dataIndex: 'page_count', width: 60 },
                {
                  title: '解析',
                  dataIndex: 'ocr_status',
                  width: 90,
                  render: (v: keyof typeof OCR_STATUS_LABELS) => (
                    <Tag color={v === 'ready' ? 'green' : v === 'failed' ? 'red' : 'blue'}>
                      {OCR_STATUS_LABELS[v] || v}
                    </Tag>
                  ),
                },
                {
                  title: '操作',
                  width: 130,
                  render: (_v, r) => (
                    <Space size={0}>
                      <Button
                        size="small"
                        type="link"
                        onClick={async () => {
                          try {
                            await openBlobInNewTab(`/files/${r.id}/preview`)
                          } catch (e) {
                            msgApi.error(normalizeError(e).message)
                          }
                        }}
                      >
                        预览
                      </Button>
                      <Button
                        size="small"
                        type="link"
                        icon={<DownloadOutlined />}
                        onClick={async () => {
                          try {
                            await downloadFile(`/files/${r.id}/download`, r.original_name)
                          } catch (e) {
                            msgApi.error(normalizeError(e).message)
                          }
                        }}
                      >
                        下载
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />

            <Divider orientation="left" style={{ margin: '4px 0' }}>
              <Space>
                <HistoryOutlined />
                版本记录（{detail.versions.length}）
              </Space>
            </Divider>
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={detail.versions}
              columns={[
                { title: '版本', dataIndex: 'version_no', width: 70, render: (v) => `V${v}` },
                { title: '标识', dataIndex: 'version_label', width: 120 },
                { title: '变更说明', dataIndex: 'change_note', ellipsis: true },
                {
                  title: '当前',
                  dataIndex: 'is_current',
                  width: 70,
                  render: (v: boolean) => (v ? <Tag color="green">当前</Tag> : '-'),
                },
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  width: 150,
                  render: (v: string) => String(v).replace('T', ' ').slice(0, 16),
                },
                {
                  title: '操作',
                  width: 90,
                  render: (_v, r) =>
                    has('doc:edit') && !r.is_current ? (
                      <Popconfirm
                        title={`回滚到 V${r.version_no}？`}
                        onConfirm={async () => {
                          try {
                            await http.post(`/documents/${detail.id}/versions/${r.id}/rollback`)
                            msgApi.success('已回滚')
                            void reloadDetail(detail.id)
                          } catch (e) {
                            msgApi.error(normalizeError(e).message)
                          }
                        }}
                      >
                        <Button size="small" type="link">
                          回滚
                        </Button>
                      </Popconfirm>
                    ) : null,
                },
              ]}
            />
          </Space>
        )}
      </Drawer>

      {versionOpen && (
        <AddVersionModal
          doc={versionOpen}
          onClose={() => setVersionOpen(null)}
          onDone={() => {
            setVersionOpen(null)
            if (detailId) void reloadDetail(detailId)
          }}
        />
      )}
    </Space>
  )
}

/** 上传资料弹窗：一次可传多个文件，FormData 直传 */
const UploadModal: React.FC<{
  rooms: Room[]
  defaultRoomId?: number
  onClose: () => void
  onDone: () => void
}> = ({ rooms, defaultRoomId, onClose, onDone }) => {
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()
  const [categories, setCategories] = useState<Category[]>([])
  const roomId = Form.useWatch('room_id', form)

  useEffect(() => {
    if (!roomId) {
      setCategories([])
      return
    }
    http
      .get<any>('/categories/tree', { params: { room_id: roomId } })
      .then(({ data }) =>
        setCategories(Array.isArray(data) ? data : (data?.rooms ?? []).flatMap((r: any) => r?.categories ?? [])),
      )
      .catch(() => setCategories([]))
  }, [roomId])

  const submit = async () => {
    try {
      const values = await form.validateFields()
      if (!fileList.length) {
        msgApi.warning('请至少选择一个文件')
        return
      }
      const fd = new FormData()
      fd.append('room_id', String(values.room_id))
      fd.append('title', values.title)
      fd.append('secrecy_level', values.secrecy_level)
      if (values.category_id) fd.append('category_id', String(values.category_id))
      if (values.doc_no) fd.append('doc_no', values.doc_no)
      if (values.summary) fd.append('summary', values.summary)
      if (values.keywords) fd.append('keywords', values.keywords)
      if (values.archive_year) fd.append('archive_year', String(values.archive_year))
      if (values.retention_years) fd.append('retention_years', String(values.retention_years))
      if (values.change_note) fd.append('change_note', values.change_note)
      fileList.forEach((f) => fd.append('files', f.originFileObj as File))
      setLoading(true)
      await http.post('/documents/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      msgApi.success('上传成功，后台开始解析')
      onDone()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="上传资料"
      open
      width={640}
      onCancel={onClose}
      onOk={submit}
      confirmLoading={loading}
      okText="上传"
      destroyOnClose
    >
      {holder}
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ secrecy_level: 'internal', room_id: defaultRoomId }}
      >
        <Row gutter={8}>
          <Col span={12}>
            <Form.Item name="room_id" label="资料室" rules={[{ required: true, message: '请选择资料室' }]}>
              <Select options={rooms.map((r) => ({ value: r.id, label: `${r.name}（${r.code}）` }))} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="category_id" label="类目">
              <TreeSelect
                allowClear
                treeData={flattenCategoryTree(categories)}
                disabled={!roomId}
                treeDefaultExpandAll
                placeholder="可选"
              />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="title" label="题名" rules={[{ required: true, message: '请输入题名' }]}>
          <Input maxLength={500} />
        </Form.Item>
        <Row gutter={8}>
          <Col span={12}>
            <Form.Item name="secrecy_level" label="密级" rules={[{ required: true }]}>
              <Select options={SECRECY_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="doc_no" label="档号" tooltip="留空则由系统按 室编码-年度-流水 自动生成">
              <Input placeholder="可留空自动生成" />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={8}>
          <Col span={12}>
            <Form.Item name="archive_year" label="归档年度">
              <InputNumber style={{ width: '100%' }} min={1900} max={2100} placeholder="默认当前年" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="retention_years" label="保管期限（年）">
              <InputNumber style={{ width: '100%' }} min={1} max={100} placeholder="默认 30" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="keywords" label="关键词">
          <Input placeholder="空格或逗号分隔" />
        </Form.Item>
        <Form.Item name="summary" label="摘要">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item label="电子文件" required>
          <Upload
            multiple
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: fl }) => setFileList(fl)}
            onRemove={(f) => setFileList((prev) => prev.filter((x) => x.uid !== f.uid))}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            支持 PDF / Word / Excel / 图片等，单份资料最多 20 个文件
          </Typography.Text>
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 新增版本：同一份资料追加文件，形成新版本 */
const AddVersionModal: React.FC<{ doc: DocumentDetail; onClose: () => void; onDone: () => void }> = ({
  doc,
  onClose,
  onDone,
}) => {
  const [fileList, setFileList] = useState<any[]>([])
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()

  const submit = async () => {
    if (!fileList.length) {
      msgApi.warning('请选择文件')
      return
    }
    const fd = new FormData()
    fileList.forEach((f) => fd.append('files', f.originFileObj as File))
    if (note) fd.append('change_note', note)
    setLoading(true)
    try {
      await http.post(`/documents/${doc.id}/versions`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      msgApi.success('新版本已提交')
      onDone()
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title={`新增版本 - ${doc.doc_no}`}
      open
      onCancel={onClose}
      onOk={submit}
      confirmLoading={loading}
      okText="提交"
      destroyOnClose
    >
      {holder}
      <Form layout="vertical">
        <Form.Item label="变更说明">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="如：修订第 3 章数据" />
        </Form.Item>
        <Form.Item label="本版本文件" required>
          <Upload
            multiple
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: fl }) => setFileList(fl)}
            onRemove={(f) => setFileList((prev) => prev.filter((x) => x.uid !== f.uid))}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 借阅申请弹窗 */
export const BorrowApplyModal: React.FC<{
  doc: DocumentBrief
  onClose: () => void
  onDone: () => void
}> = ({ doc, onClose, onDone }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [msgApi, holder] = message.useMessage()

  const submit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      await http.post('/borrow/requests', {
        document_id: doc.id,
        reason: values.reason,
        days: values.days,
        can_download: !!values.can_download,
        can_print: !!values.can_print,
      })
      msgApi.success('借阅申请已提交，等待审批')
      onDone()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="申请借阅"
      open
      onCancel={onClose}
      onOk={submit}
      confirmLoading={loading}
      okText="提交申请"
      destroyOnClose
    >
      {holder}
      <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="档号">{doc.doc_no}</Descriptions.Item>
        <Descriptions.Item label="题名">{doc.title}</Descriptions.Item>
        <Descriptions.Item label="密级">
          <Tag color={SECRECY_COLORS[doc.secrecy_level]}>{SECRECY_LABELS[doc.secrecy_level]}</Tag>
        </Descriptions.Item>
      </Descriptions>
      <Form form={form} layout="vertical" preserve={false} initialValues={{ days: 7 }}>
        <Form.Item
          name="reason"
          label="借阅事由"
          rules={[{ required: true, message: '请填写借阅事由' }, { min: 2, message: '至少 2 个字' }]}
        >
          <Input.TextArea rows={3} maxLength={2000} showCount placeholder="请说明用途，便于审批人判断" />
        </Form.Item>
        <Form.Item name="days" label="借阅天数" rules={[{ required: true }]}>
          <InputNumber min={1} max={90} style={{ width: '100%' }} addonAfter="天" />
        </Form.Item>
        <Form.Item name="can_download" label="申请下载权" valuePropName="checked">
          <Select
            options={[
              { value: false, label: '仅在线查看' },
              { value: true, label: '允许下载' },
            ]}
          />
        </Form.Item>
        <Form.Item name="can_print" label="申请打印权" valuePropName="checked">
          <Select
            options={[
              { value: false, label: '不申请' },
              { value: true, label: '允许打印' },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default Documents
