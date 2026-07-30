import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import Layout from '@/components/Layout';
import LoginPage from '@/pages/LoginPage';
import { useAuthStore } from '@/stores/authStore';

// 代码分割: 懒加载非首页路由
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const ChatPage = lazy(() => import('@/pages/ChatPage'));
const MetricsPage = lazy(() => import('@/pages/MetricsPage'));
const DataManagementPage = lazy(() => import('@/pages/DataManagementPage'));
const AdminPage = lazy(() => import('@/pages/AdminPage'));

const PageLoader = () => <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>;

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, checkAuth } = useAuthStore();
  if (!token && !checkAuth()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const { token, checkAuth } = useAuthStore();

  if (!token && !checkAuth()) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={
        <ProtectedRoute><Layout /></ProtectedRoute>
      }>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Suspense fallback={<PageLoader />}><DashboardPage /></Suspense>} />
        <Route path="chat" element={<Suspense fallback={<PageLoader />}><ChatPage /></Suspense>} />
        <Route path="metrics" element={<Suspense fallback={<PageLoader />}><MetricsPage /></Suspense>} />
        <Route path="data" element={<Suspense fallback={<PageLoader />}><DataManagementPage /></Suspense>} />
        <Route path="admin" element={<Suspense fallback={<PageLoader />}><AdminPage /></Suspense>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
