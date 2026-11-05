import React, { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppLayout } from './layout/AppLayout'
import Login from './pages/Login'
import ChangePassword from './pages/ChangePassword'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Documents = lazy(() => import('./pages/Documents'))
const Search = lazy(() => import('./pages/Search'))
const Borrow = lazy(() => import('./pages/Borrow'))
const Rooms = lazy(() => import('./pages/Rooms'))
const Users = lazy(() => import('./pages/Users'))
const Audit = lazy(() => import('./pages/Audit'))
const Backups = lazy(() => import('./pages/Backups'))
const SystemCheck = lazy(() => import('./pages/SystemCheck'))

function PageFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 120 }}>
      <Spin size="large" />
    </div>
  )
}

/** 登录保护：未登录跳登录页，并记录原始目标地址 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

/** 权限保护：无权限时回首页，避免空白页 */
function RequirePermission({ perm, children }: { perm: string; children: React.ReactNode }) {
  const { has } = useAuth()
  if (!has(perm)) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/change-password"
            element={
              <RequireAuth>
                <ChangePassword />
              </RequireAuth>
            }
          />
          <Route
            path="/"
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route index element={<Dashboard />} />
            <Route
              path="documents"
              element={
                <RequirePermission perm="doc:view">
                  <Documents />
                </RequirePermission>
              }
            />
            <Route
              path="search"
              element={
                <RequirePermission perm="doc:view">
                  <Search />
                </RequirePermission>
              }
            />
            <Route
              path="borrow"
              element={
                <RequirePermission perm="borrow:apply">
                  <Borrow />
                </RequirePermission>
              }
            />
            <Route
              path="rooms"
              element={
                <RequirePermission perm="room:manage">
                  <Rooms />
                </RequirePermission>
              }
            />
            <Route
              path="users"
              element={
                <RequirePermission perm="user:manage">
                  <Users />
                </RequirePermission>
              }
            />
            <Route
              path="audit"
              element={
                <RequirePermission perm="audit:view">
                  <Audit />
                </RequirePermission>
              }
            />
            <Route
              path="backups"
              element={
                <RequirePermission perm="backup:manage">
                  <Backups />
                </RequirePermission>
              }
            />
            <Route path="health" element={<SystemCheck />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AuthProvider>
  )
}
