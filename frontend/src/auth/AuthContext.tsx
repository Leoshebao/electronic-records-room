import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { http, normalizeError, setUnauthorizedHandler, tokenStore } from '../api/client'
import type { TokenResponse, UserBrief } from '../api/types'

interface AuthState {
  user: UserBrief | null
  loading: boolean
  login: (username: string, password: string) => Promise<UserBrief>
  logout: () => Promise<void>
  refreshMe: () => Promise<UserBrief | null>
  has: (permission: string) => boolean
}

const AuthContext = createContext<AuthState>({} as AuthState)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserBrief | null>(() => tokenStore.getUser())
  const [loading, setLoading] = useState(true)

  const logout = useCallback(async () => {
    try {
      await http.post('/auth/logout')
    } catch {
      /* 忽略：token 可能已失效 */
    }
    tokenStore.clear()
    setUser(null)
  }, [])

  const refreshMe = useCallback(async () => {
    if (!tokenStore.get()) {
      setLoading(false)
      return null
    }
    try {
      const { data } = await http.get<UserBrief>('/auth/me')
      setUser(data)
      tokenStore.setUser(data)
      return data
    } catch {
      setUser(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      tokenStore.clear()
      setUser(null)
      if (!location.pathname.startsWith('/login')) {
        location.replace('/login')
      }
    })
    void refreshMe()
  }, [refreshMe])

  const login = useCallback(async (username: string, password: string) => {
    try {
      const { data } = await http.post<TokenResponse>('/auth/login', { username, password })
      tokenStore.set(data.access_token)
      tokenStore.setUser(data.user)
      setUser(data.user)
      return data.user
    } catch (e) {
      throw new Error(normalizeError(e).message)
    }
  }, [])

  const has = useCallback(
    (permission: string) => (user?.permissions || []).includes(permission),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, login, logout, refreshMe, has }),
    [user, loading, login, logout, refreshMe, has],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
