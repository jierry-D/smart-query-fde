import { useState, useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout as AntLayout, Menu, Button, Avatar, Dropdown, Space, Badge, App } from 'antd';
import {
  DashboardOutlined, MessageOutlined, UnorderedListOutlined,
  DatabaseOutlined, UploadOutlined, SettingOutlined,
  UserOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '@/stores/authStore';
import client from '@/api/client';
import type { StatusInfo } from '@/types';

const { Header, Sider, Content } = AntLayout;

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    loadStatus();
    const t = setInterval(loadStatus, 60000);
    return () => clearInterval(t);
  }, []);

  const loadStatus = async () => {
    try {
      const { data } = await client.get('/status');
      setStatus(data);
    } catch { /* silent */ }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const currentPath = location.pathname.split('/')[1] || 'dashboard';

  const roleTag = { admin: '🔧 管理员', leader: '📊 领导', employee: '👤 员工' }[user?.role || 'employee'];
  const scopeText = user?.role === 'admin' ? '全部数据'
    : user?.role === 'leader' ? `${user?.department} 全部`
    : `${user?.department}-${user?.region}`;

  const menuItems = [
    { key: 'dashboard', icon: <DashboardOutlined />, label: '经营仪表盘' },
    { key: 'chat', icon: <MessageOutlined />, label: '智能问数' },
    { key: 'metrics', icon: <UnorderedListOutlined />, label: '指标目录' },
    { key: 'data', icon: <DatabaseOutlined />, label: '数据管理' },
  ];

  if (user?.role === 'admin' || user?.role === 'leader') {
    menuItems.push({ key: 'import', icon: <UploadOutlined />, label: '导入数据' } as any);
  }
  if (user?.role === 'admin') {
    menuItems.push({ key: 'admin', icon: <SettingOutlined />, label: '系统管理' });
  }

  const userMenu: any = {
    items: [
      { key: 'info', label: `${roleTag} — ${scopeText}`, disabled: true },
      { type: 'divider' as const },
      { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, danger: true },
    ],
    onClick: (e: any) => { if (e.key === 'logout') handleLogout(); },
  };

  return (
    <AntLayout style={{ height: '100vh' }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        breakpoint="lg"
        collapsedWidth="0"
        style={{ background: '#fff', borderRight: '1px solid #f0f0f0' }}
      >
        <div style={{ height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <span style={{ fontSize: collapsed ? 18 : 16, fontWeight: 700, color: '#4f46e5' }}>
            {collapsed ? '🔍' : '🔍 智慧问数'}
          </span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[currentPath]}
          items={menuItems}
          onClick={({ key }) => navigate(`/${key}`)}
          style={{ borderInlineEnd: 'none', marginTop: 8 }}
        />
      </Sider>
      <AntLayout>
        <Header style={{
          background: '#fff', padding: '0 24px', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid #f0f0f0', height: 64,
        }}>
          <Space>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
            />
            <span style={{ color: '#8c8c8c', fontSize: 13 }}>
              {status && `📅 ${status.date} · 📦 ${status.snapshots} 快照 · 📋 ${status.metrics_available}/${status.metrics_total} 指标`}
            </span>
          </Space>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Badge status="success" dot offset={[-2, 30]}>
                <Avatar size="small" icon={<UserOutlined />} style={{ background: '#4f46e5' }} />
              </Badge>
              <span style={{ fontSize: 14 }}>{user?.display_name || user?.username}</span>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ margin: 16, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
