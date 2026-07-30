import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from '@/components/Layout';
import LoginPage from '@/pages/LoginPage';
import DashboardPage from '@/pages/DashboardPage';
import ChatPage from '@/pages/ChatPage';
import MetricsPage from '@/pages/MetricsPage';
import DataManagementPage from '@/pages/DataManagementPage';
import AdminPage from '@/pages/AdminPage';
import { useAuthStore } from '@/stores/authStore';

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
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="data" element={<DataManagementPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
