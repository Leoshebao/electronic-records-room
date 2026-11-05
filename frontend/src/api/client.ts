// 统一的 HTTP 客户端：token 注入、错误归一化、文件下载（带鉴权头）
import axios, { AxiosError, AxiosRequestConfig } from 'axios'

// 运行时配置由 index.html 注入（见 vite-env.d.ts 中的 Window.__APP_CONFIG__ 声明）
export const API_BASE = (window.__APP_CONFIG__?.API_BASE || '').replace(/\/+$/, '')
export const APP_NAME = window.__APP_CONFIG__?.APP_NAME || '电子资料室'

const TOKEN_KEY = 'erec_access_token'
const USER_KEY = 'erec_user'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
  getUser: () => {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  },
  setUser: (u: unknown) => localStorage.setItem(USER_KEY, JSON.stringify(u)),
}

export const http = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 120000,
})

http.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface ApiError {
  status: number
  message: string
  code?: string
}

export function normalizeError(err: unknown): ApiError {
  const ax = err as AxiosError<any>
  if (ax?.response) {
    const data = ax.response.data
    let msg = '请求失败'
    if (typeof data === 'string') msg = data
    else if (data?.detail) {
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } else if (data?.message) msg = data.message
    return { status: ax.response.status, message: msg, code: data?.code }
  }
  if (ax?.code === 'ECONNABORTED') return { status: 0, message: '请求超时，请稍后重试' }
  return { status: 0, message: ax?.message || '网络异常，无法连接服务器' }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

http.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response?.status === 401 && onUnauthorized) onUnauthorized()
    return Promise.reject(err)
  },
)

function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? decodeURIComponent(plain[1]) : fallback
}

/** 带鉴权下载：axios 取 blob 后触发浏览器保存，避免直链丢失 Authorization 头 */
export async function downloadFile(path: string, fallbackName = 'download', config?: AxiosRequestConfig) {
  const resp = await http.get(path, { responseType: 'blob', ...config })
  const name = filenameFromDisposition(resp.headers['content-disposition'] as string, fallbackName)
  const url = URL.createObjectURL(resp.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 3000)
}

/** 预览：取 blob 后在新标签打开 */
export async function openBlobInNewTab(path: string, config?: AxiosRequestConfig) {
  const resp = await http.get(path, { responseType: 'blob', ...config })
  const url = URL.createObjectURL(resp.data as Blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
