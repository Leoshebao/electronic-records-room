import React, { useCallback, useEffect, useState } from 'react'
import {
  Card, Col, Empty, Input, List, Pagination, Row, Select, Space, Spin, Tag, Typography, Button, message,
} from 'antd'
import { SearchOutlined, SwapOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { http, normalizeError } from '../api/client'
import { SECRECY_COLORS, SECRECY_LABELS, type Room, type SearchHit, type SearchPage, type SecrecyLevel } from '../api/types'
import { BorrowApplyModal } from './Documents'

const SECRECY_OPTIONS = (Object.keys(SECRECY_LABELS) as SecrecyLevel[]).map((v) => ({
  value: v,
  label: SECRECY_LABELS[v],
}))

/** snippet 由后端生成，仅保留 <mark> 高亮，其余标签一律转义，避免注入 */
function renderSnippet(text: string | null | undefined): string {
  if (!text) return ''
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped
    .replace(/&lt;(\/?)(mark|em|b|strong)&gt;/g, '<$1$2>')
}

const Search: React.FC = () => {
  const navigate = useNavigate()
  const [msgApi, holder] = message.useMessage()
  const [q, setQ] = useState('')
  const [roomId, setRoomId] = useState<number | undefined>()
  const [level, setLevel] = useState<string | undefined>()
  const [year, setYear] = useState<number | undefined>()
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(10)
  const [data, setData] = useState<SearchPage | null>(null)
  const [rooms, setRooms] = useState<Room[]>([])
  const [loading, setLoading] = useState(false)
  const [borrowDoc, setBorrowDoc] = useState<SearchHit | null>(null)
  const [searched, setSearched] = useState(false)

  const run = useCallback(
    async (nextPage = 1, nextQ?: string) => {
      const keyword = (nextQ ?? q).trim()
      if (!keyword) {
        msgApi.warning('请输入检索关键词')
        return
      }
      setLoading(true)
      setSearched(true)
      try {
        const { data: resp } = await http.get<SearchPage>('/search', {
          params: {
            q: keyword,
            room_id: roomId,
            secrecy_level: level,
            archive_year: year,
            page: nextPage,
            size,
            sort: 'relevance',
            order: 'desc',
          },
        })
        setData(resp)
        setPage(nextPage)
      } catch (e) {
        msgApi.error(normalizeError(e).message)
      } finally {
        setLoading(false)
      }
    },
    [q, roomId, level, year, size, msgApi],
  )

  useEffect(() => {
    http
      .get<Room[]>('/rooms')
      .then(({ data }) => setRooms(data))
      .catch(() => setRooms([]))
  }, [])

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {holder}
      <Card size="small">
        <Input
          size="large"
          allowClear
          prefix={<SearchOutlined />}
          placeholder="输入关键词，多个关键词用空格分隔（支持档号、题名、摘要、正文全文）"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onPressEnter={() => void run(1)}
          addonAfter={
            <Button type="link" size="small" onClick={() => void run(1)}>
              检索
            </Button>
          }
        />
        <Row gutter={[8, 8]} style={{ marginTop: 8 }}>
          <Col xs={12} md={6}>
            <Select
              allowClear
              placeholder="资料室"
              style={{ width: '100%' }}
              value={roomId}
              onChange={setRoomId}
              options={rooms.map((r) => ({ value: r.id, label: r.name }))}
            />
          </Col>
          <Col xs={12} md={6}>
            <Select
              allowClear
              placeholder="密级"
              style={{ width: '100%' }}
              value={level}
              onChange={setLevel}
              options={SECRECY_OPTIONS}
            />
          </Col>
          <Col xs={12} md={6}>
            <Select
              allowClear
              placeholder="归档年度"
              style={{ width: '100%' }}
              value={year}
              onChange={setYear}
              options={Array.from({ length: 20 }, (_, i) => new Date().getFullYear() - i).map((y) => ({
                value: y,
                label: `${y} 年`,
              }))}
            />
          </Col>
          <Col xs={12} md={6}>
            <Button type="primary" block onClick={() => void run(1)}>
              应用筛选
            </Button>
          </Col>
        </Row>
      </Card>

      {loading && <Spin style={{ display: 'block', margin: '60px auto' }} />}

      {!loading && searched && data && (
        <Card size="small">
          <Space split="·" wrap>
            <Typography.Text strong>命中 {data.meta.total} 条</Typography.Text>
            <Typography.Text type="secondary">耗时 {data.took_ms} ms</Typography.Text>
            <Typography.Text type="secondary">
              分词：{data.keywords.join(' / ') || '-'}
            </Typography.Text>
            <Tag color={data.trgm ? 'green' : 'default'}>pg_trgm {data.trgm ? '启用' : '未启用'}</Tag>
            <Tag color={data.fts ? 'green' : 'default'}>全文索引 {data.fts ? '启用' : '未启用'}</Tag>
          </Space>
        </Card>
      )}

      {!loading && searched && data && data.items.length === 0 && (
        <Empty description="没有匹配的资料，试试更换关键词或放宽筛选" />
      )}

      {!loading && data && data.items.length > 0 && (
        <>
          <List
            itemLayout="vertical"
            dataSource={data.items}
            renderItem={(item) => (
              <Card size="small" style={{ marginBottom: 8 }}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Space wrap>
                    <a style={{ fontSize: 15, fontWeight: 600 }} onClick={() => navigate(`/documents?doc=${item.id}`)}>
                      {item.title}
                    </a>
                    <Tag>{item.doc_no}</Tag>
                    <Tag color={SECRECY_COLORS[item.secrecy_level]}>{SECRECY_LABELS[item.secrecy_level]}</Tag>
                    {item.archive_year && <Tag color="blue">{item.archive_year} 年</Tag>}
                    {item.matched?.map((m) => (
                      <Tag key={m} color="purple">
                        命中 {m}
                      </Tag>
                    ))}
                  </Space>
                  {item.snippet && (
                    <div
                      className="search-snippet"
                      style={{
                        margin: 0,
                        color: 'rgba(0, 0, 0, 0.65)',
                        fontSize: 14,
                        lineHeight: 1.5715,
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                      dangerouslySetInnerHTML={{ __html: renderSnippet(item.snippet) }}
                    />
                  )}
                  <Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      文件 {item.file_count} · 页数 {item.page_count} · 浏览 {item.view_count}
                    </Typography.Text>
                    <Button size="small" type="link" onClick={() => navigate(`/documents?doc=${item.id}`)}>
                      查看详情
                    </Button>
                    <Button size="small" type="link" icon={<SwapOutlined />} onClick={() => setBorrowDoc(item)}>
                      申请借阅
                    </Button>
                  </Space>
                </Space>
              </Card>
            )}
          />
          <Pagination
            current={page}
            pageSize={size}
            total={data.meta.total}
            showSizeChanger
            pageSizeOptions={[10, 20, 50]}
            onChange={(p, s) => {
              setSize(s)
              void run(p)
            }}
            style={{ textAlign: 'right' }}
          />
        </>
      )}

      {!searched && (
        <Card>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            提示：检索范围受账号密级限制，仅返回当前账号有权查看的资料；正文检索依赖 OCR 解析结果，
            刚上传的文件需等待后台解析完成。
          </Typography.Paragraph>
        </Card>
      )}

      {borrowDoc && (
        <BorrowApplyModal doc={borrowDoc} onClose={() => setBorrowDoc(null)} onDone={() => setBorrowDoc(null)} />
      )}
    </Space>
  )
}

export default Search
