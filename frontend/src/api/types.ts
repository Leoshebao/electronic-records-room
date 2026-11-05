// 与后端 Pydantic Schema 对齐的类型定义（字段名保持后端原样，避免二次映射）

export type Role = 'sysadmin' | 'records_manager' | 'viewer'
export type SecrecyLevel = 'public' | 'internal' | 'secret' | 'confidential'
export type DocStatus = 'draft' | 'active' | 'archived' | 'destroyed'
export type OCRStatus = 'queued' | 'processing' | 'ready' | 'failed' | 'skipped'
export type FileStatus = 'pending' | 'stored' | 'missing' | 'deleted'
export type BorrowStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'returned'
  | 'expired'
  | 'cancelled'

export interface UserBrief {
  id: number
  username: string
  full_name: string
  role: Role
  role_label: string
  department_name?: string | null
  must_change_password: boolean
  permissions: string[]
  max_secrecy_level: SecrecyLevel
  visible_levels: SecrecyLevel[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  must_change_password: boolean
  user: UserBrief
}

export interface Room {
  id: number
  name: string
  code: string
  description?: string | null
  location?: string | null
  keeper_id?: number | null
  keeper_name?: string | null
  is_active: boolean
  sort_order: number
  doc_count: number
}

export interface Category {
  id: number
  room_id: number
  parent_id: number | null
  name: string
  code?: string | null
  level: number
  path: string
  remark?: string | null
  sort_order: number
  children: Category[]
}

export interface FileBrief {
  id: number
  document_id: number
  version_id?: number | null
  original_name: string
  ext: string
  mime_type?: string | null
  size_bytes: number
  page_count: number
  status: FileStatus
  ocr_status: OCRStatus
  created_at: string
}

export interface VersionBrief {
  id: number
  version_no: number
  version_label?: string | null
  change_note?: string | null
  is_current: boolean
  created_by: number
  created_at: string
}

export interface DocumentBrief {
  id: number
  doc_no: string
  title: string
  room_id: number
  category_id?: number | null
  secrecy_level: SecrecyLevel
  status: DocStatus
  summary?: string | null
  keywords?: string | null
  archive_year?: number | null
  retention_years?: number | null
  file_count: number
  total_size: number
  page_count: number
  view_count: number
  download_count: number
  created_by: number
  created_at: string
  updated_at?: string | null
}

export interface DocumentDetail extends DocumentBrief {
  current_version_id?: number | null
  responsible_dept_id?: number | null
  files: FileBrief[]
  versions: VersionBrief[]
}

export interface PageMeta {
  total: number
  page: number
  size: number
  pages: number
}

export interface DocumentPage {
  items: DocumentBrief[]
  meta: PageMeta
}

export interface SearchHit extends DocumentBrief {
  score?: number | null
  snippet?: string | null
  matched: string[]
}

export interface SearchPage {
  items: SearchHit[]
  meta: PageMeta
  query: string
  keywords: string[]
  took_ms: number
  trgm: boolean
  fts: boolean
}

export interface SuggestItem {
  id: number
  doc_no: string
  title: string
  secrecy_level: SecrecyLevel
}

export interface BorrowRequest {
  id: number
  request_no: string
  document_id: number
  doc_no?: string | null
  title?: string | null
  secrecy_level?: string | null
  applicant_id: number
  applicant_name?: string | null
  reason: string
  status: BorrowStatus
  requested_days: number
  want_download: boolean
  want_print: boolean
  approver_id?: number | null
  approved_at?: string | null
  reject_reason?: string | null
  start_at?: string | null
  due_at?: string | null
  returned_at?: string | null
  renew_count: number
  remaining_days: number
  created_at?: string | null
}

export interface BorrowPage {
  items: BorrowRequest[]
  total: number
  page: number
  size: number
  pages: number
  pending_total: number
}

export interface AuditLog {
  id: number
  user_id?: number | null
  username?: string | null
  action: string
  target_type?: string | null
  target_id?: number | null
  detail?: Record<string, unknown> | null
  ip_address?: string | null
  user_agent?: string | null
  result: string
  created_at: string
}

export interface AuditPage {
  items: AuditLog[]
  total: number
  page: number
  size: number
}

export interface AuditActionItem {
  action: string
  label: string
  count: number
}

export interface AuditSummary {
  total: number
  today: number
  failed: number
  by_action: AuditActionItem[]
  by_user: Array<Record<string, unknown>>
}

export interface UserOut {
  id: number
  username: string
  full_name: string
  role: Role
  department_id?: number | null
  department_name?: string | null
  email?: string | null
  phone?: string | null
  is_active: boolean
  must_change_password: boolean
  last_login_at?: string | null
  created_at: string
}

export interface Department {
  id: number
  name: string
  code?: string | null
  parent_id?: number | null
  sort_order: number
  is_active: boolean
}

export interface BackupOut {
  id: number
  filename: string
  file_path: string
  backup_type: string
  size_bytes: number
  status: string
  error_msg?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

export interface BackupList {
  items: BackupOut[]
  total: number
  backup_root: string
  keep_days: number
}

export interface OcrTask {
  id: number
  file_id: number
  document_id?: number | null
  status: OCRStatus
  engine?: string | null
  retry_count?: number
  error_msg?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

export interface StatsOverview {
  documents: Record<string, any>
  storage: Record<string, any>
  borrow: Record<string, any>
  ocr: Record<string, any>
  users: Record<string, any>
  trend: Array<Record<string, any>>
  top_documents: Array<Record<string, any>>
}

export const SECRECY_LABELS: Record<SecrecyLevel, string> = {
  public: '公开',
  internal: '内部',
  secret: '秘密',
  confidential: '机密',
}

export const SECRECY_COLORS: Record<SecrecyLevel, string> = {
  public: 'green',
  internal: 'blue',
  secret: 'orange',
  confidential: 'red',
}

export const DOC_STATUS_LABELS: Record<DocStatus, string> = {
  draft: '草稿',
  active: '在库',
  archived: '已归档',
  destroyed: '已销毁',
}

export const BORROW_STATUS_LABELS: Record<BorrowStatus, string> = {
  pending: '待审批',
  approved: '借阅中',
  rejected: '已驳回',
  returned: '已归还',
  expired: '已到期',
  cancelled: '已撤回',
}

export const BORROW_STATUS_COLORS: Record<BorrowStatus, string> = {
  pending: 'gold',
  approved: 'blue',
  rejected: 'red',
  returned: 'green',
  expired: 'default',
  cancelled: 'default',
}

export const OCR_STATUS_LABELS: Record<OCRStatus, string> = {
  queued: '排队中',
  processing: '解析中',
  ready: '已完成',
  failed: '失败',
  skipped: '已跳过',
}

export const ROLE_LABELS: Record<Role, string> = {
  sysadmin: '系统管理员',
  records_manager: '档案管理员',
  viewer: '查阅者',
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}
