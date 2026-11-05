import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Empty, Form, Input, InputNumber, Modal, Popconfirm, Row, Space, Switch,
  Table, Tag, Tooltip, Tree, Typography, message, Badge,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined, ApartmentOutlined, FolderOutlined,
} from '@ant-design/icons'
import { http, normalizeError } from '../api/client'
import type { Category, Room } from '../api/types'

const Rooms: React.FC = () => {
  const [msgApi, holder] = message.useMessage()
  const [rooms, setRooms] = useState<Room[]>([])
  const [loading, setLoading] = useState(false)
  const [includeInactive, setIncludeInactive] = useState(false)
  const [selected, setSelected] = useState<Room | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [catLoading, setCatLoading] = useState(false)

  const [roomModal, setRoomModal] = useState<{ open: boolean; room?: Room }>({ open: false })
  const [catModal, setCatModal] = useState<{ open: boolean; parent?: Category | null; cat?: Category }>({
    open: false,
  })
  const [roomForm] = Form.useForm()
  const [catForm] = Form.useForm()

  const loadRooms = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await http.get<Room[]>('/rooms', { params: { include_inactive: includeInactive } })
      setRooms(data)
      if (!selected && data.length) setSelected(data[0])
      else if (selected) {
        const fresh = data.find((r) => r.id === selected.id)
        if (fresh) setSelected(fresh)
      }
    } catch (e) {
      msgApi.error(normalizeError(e).message)
    } finally {
      setLoading(false)
    }
  }, [includeInactive, selected, msgApi])

  const loadCategories = useCallback(
    async (roomId?: number) => {
      if (!roomId) {
        setCategories([])
        return
      }
      setCatLoading(true)
      try {
        const { data } = await http.get<Category[]>('/categories/tree', { params: { room_id: roomId } })
        setCategories(data)
      } catch (e) {
        msgApi.error(normalizeError(e).message)
      } finally {
        setCatLoading(false)
      }
    },
    [msgApi],
  )

  useEffect(() => {
    void loadRooms()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeInactive])

  useEffect(() => {
    void loadCategories(selected?.id)
  }, [selected?.id, loadCategories])

  const openRoomModal = (room?: Room) => {
    setRoomModal({ open: true, room })
    roomForm.setFieldsValue(
      room
        ? {
            name: room.name,
            description: room.description,
            location: room.location,
            sort_order: room.sort_order,
            is_active: room.is_active,
          }
        : { sort_order: 0 },
    )
  }

  const submitRoom = async () => {
    try {
      const v = await roomForm.validateFields()
      if (roomModal.room) {
        await http.patch(`/rooms/${roomModal.room.id}`, v)
        msgApi.success('资料室已更新')
      } else {
        await http.post('/rooms', v)
        msgApi.success('资料室已创建')
      }
      setRoomModal({ open: false })
      await loadRooms()
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    }
  }

  const submitCat = async () => {
    try {
      const v = await catForm.validateFields()
      if (catModal.cat) {
        await http.patch(`/categories/${catModal.cat.id}`, v)
        msgApi.success('类目已更新')
      } else {
        await http.post('/categories', {
          ...v,
          room_id: selected?.id,
          parent_id: catModal.parent?.id ?? null,
        })
        msgApi.success('类目已创建')
      }
      setCatModal({ open: false })
      void loadCategories(selected?.id)
    } catch (e: any) {
      if (e instanceof Error && e.message) msgApi.error(normalizeError(e).message)
    }
  }

  const openCatModal = (parent?: Category | null, cat?: Category) => {
    setCatModal({ open: true, parent, cat })
    catForm.setFieldsValue(
      cat ? { name: cat.name, code: cat.code, remark: cat.remark, sort_order: cat.sort_order } : { sort_order: 0 },
    )
  }

  const toTreeData = (nodes: Category[]): DataNode[] =>
    nodes.map((n) => ({
      key: n.id,
      title: (
        <Space size={6}>
          <FolderOutlined style={{ color: '#1677ff' }} />
          <span>{n.name}</span>
          {n.code && <Tag style={{ marginInlineEnd: 0 }}>{n.code}</Tag>}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            L{n.level}
          </Typography.Text>
          <Space size={0} className="tree-actions">
            {n.level < 3 && (
              <Tooltip title="新增子类目">
                <Button
                  size="small"
                  type="text"
                  icon={<PlusOutlined />}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    openCatModal(n)
                  }}
                />
              </Tooltip>
            )}
            <Tooltip title="编辑">
              <Button
                size="small"
                type="text"
                icon={<EditOutlined />}
                onClick={(ev) => {
                  ev.stopPropagation()
                  openCatModal(null, n)
                }}
              />
            </Tooltip>
            <Popconfirm
              title="删除该类目？"
              description="仅当类目下无资料、无子类目时可删除"
              onConfirm={async () => {
                try {
                  await http.delete(`/categories/${n.id}`)
                  msgApi.success('已删除')
                  void loadCategories(selected?.id)
                } catch (e) {
                  msgApi.error(normalizeError(e).message)
                }
              }}
            >
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={(ev) => ev.stopPropagation()}
              />
            </Popconfirm>
          </Space>
        </Space>
      ),
      children: n.children?.length ? toTreeData(n.children) : undefined,
    }))

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Row gutter={12}>
        <Col xs={24} lg={13}>
          <Card
            size="small"
            title="资料室"
            extra={
              <Space>
                <Space size={4}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    含停用
                  </Typography.Text>
                  <Switch size="small" checked={includeInactive} onChange={setIncludeInactive} />
                </Space>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadRooms()}>
                  刷新
                </Button>
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => openRoomModal()}>
                  新建资料室
                </Button>
              </Space>
            }
          >
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={rooms}
              pagination={false}
              rowClassName={(r) => (r.id === selected?.id ? 'row-selected' : '')}
              onRow={(r) => ({ onClick: () => setSelected(r), style: { cursor: 'pointer' } })}
              columns={[
                {
                  title: '名称',
                  dataIndex: 'name',
                  render: (v, r) => (
                    <Space direction="vertical" size={0}>
                      <Space size={6}>
                        <span>{v}</span>
                        {!r.is_active && <Tag>已停用</Tag>}
                      </Space>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {r.code} {r.location ? `· ${r.location}` : ''}
                      </Typography.Text>
                    </Space>
                  ),
                },
                {
                  title: '保管人',
                  dataIndex: 'keeper_name',
                  width: 90,
                  render: (v) => v || '-',
                },
                {
                  title: '资料数',
                  dataIndex: 'doc_count',
                  width: 80,
                  align: 'center',
                  render: (v: number) => <Badge count={v} showZero color="#1677ff" />,
                },
                {
                  title: '操作',
                  width: 110,
                  render: (_v, r) => (
                    <Space size={0}>
                      <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); openRoomModal(r) }}>
                        编辑
                      </Button>
                      <Popconfirm
                        title="删除该资料室？"
                        description="室内有资料时不允许删除，建议改为停用"
                        onConfirm={async () => {
                          try {
                            await http.delete(`/rooms/${r.id}`)
                            msgApi.success('已删除')
                            if (selected?.id === r.id) setSelected(null)
                            void loadRooms()
                          } catch (e) {
                            msgApi.error(normalizeError(e).message)
                          }
                        }}
                      >
                        <Button size="small" type="link" danger onClick={(e) => e.stopPropagation()}>
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={11}>
          <Card
            size="small"
            title={
              <Space>
                <ApartmentOutlined />
                类目树{selected ? ` · ${selected.name}` : ''}
              </Space>
            }
            extra={
              <Space>
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={() => void loadCategories(selected?.id)}
                  disabled={!selected}
                >
                  刷新
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<PlusOutlined />}
                  disabled={!selected}
                  onClick={() => openCatModal(null)}
                >
                  新建一级类目
                </Button>
              </Space>
            }
            loading={catLoading}
          >
            {!selected && <Empty description="请选择左侧资料室" />}
            {selected && categories.length === 0 && (
              <Empty description="暂未建类目，可直接上传资料或先建一级类目（最多三级）" />
            )}
            {selected && categories.length > 0 && (
              <Tree
                treeData={toTreeData(categories)}
                defaultExpandAll
                blockNode
                selectable={false}
                style={{ fontSize: 14 }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title={roomModal.room ? `编辑资料室 - ${roomModal.room.name}` : '新建资料室'}
        open={roomModal.open}
        onCancel={() => setRoomModal({ open: false })}
        onOk={submitRoom}
        okText="保存"
        destroyOnClose
      >
        <Form form={roomForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} placeholder="如：综合档案室" />
          </Form.Item>
          {!roomModal.room && (
            <Form.Item
              name="code"
              label="编码"
              rules={[
                { required: true, message: '请输入编码' },
                { pattern: /^[A-Za-z0-9_-]+$/, message: '仅字母、数字、下划线、短横线' },
              ]}
              tooltip="用于生成档号前缀，创建后不可修改"
            >
              <Input maxLength={32} placeholder="如：ZH" />
            </Form.Item>
          )}
          <Form.Item name="location" label="位置">
            <Input maxLength={200} placeholder="如：三楼 305" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item name="sort_order" label="排序值">
                <InputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </Col>
            {roomModal.room && (
              <Col span={12}>
                <Form.Item name="is_active" label="启用状态" valuePropName="checked">
                  <Switch checkedChildren="启用" unCheckedChildren="停用" />
                </Form.Item>
              </Col>
            )}
          </Row>
        </Form>
      </Modal>

      <Modal
        title={catModal.cat ? `编辑类目 - ${catModal.cat.name}` : catModal.parent ? `新增子类目（父：${catModal.parent.name}）` : '新建一级类目'}
        open={catModal.open}
        onCancel={() => setCatModal({ open: false })}
        onOk={submitCat}
        okText="保存"
        destroyOnClose
      >
        <Form form={catForm} layout="vertical" preserve={false}>
          <Form.Item name="name" label="类目名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="code" label="类目编码">
            <Input maxLength={32} placeholder="可留空" />
          </Form.Item>
          <Form.Item name="sort_order" label="排序值">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

export default Rooms
