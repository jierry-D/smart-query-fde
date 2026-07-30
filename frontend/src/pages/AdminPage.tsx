import { useState, useEffect } from 'react';
import { Tabs, Table, Card, Statistic, Row, Col, Spin, Typography, Tag } from 'antd';
import client from '@/api/client';
import type { QueryLog, AdminStats } from '@/types';

const { Title, Text } = Typography;

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('stats');
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<any[]>([]);
  const [logs, setLogs] = useState<QueryLog[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (activeTab === 'stats') loadStats();
    if (activeTab === 'users') loadUsers();
    if (activeTab === 'logs') loadLogs();
  }, [activeTab]);

  const loadStats = async () => {
    setLoading(true);
    try {
      const { data } = await client.get('/admin/stats');
      setStats(data);
    } catch { /* no data */ }
    setLoading(false);
  };

  const loadUsers = async () => {
    setLoading(true);
    try {
      const { data } = await client.get('/admin/users');
      setUsers(data.users || []);
    } catch { /* no data */ }
    setLoading(false);
  };

  const loadLogs = async () => {
    setLoading(true);
    try {
      const { data } = await client.get('/admin/logs');
      setLogs(data.logs || []);
    } catch { /* no data */ }
    setLoading(false);
  };

  const userColumns = [
    { title: 'ID', dataIndex: 'user_id', key: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '显示名', dataIndex: 'display_name', key: 'display' },
    { title: '角色', dataIndex: 'role', key: 'role', render: (v: string) =>
      <Tag color={v === 'admin' ? 'red' : v === 'leader' ? 'blue' : 'green'}>{v}</Tag> },
    { title: '部门', dataIndex: 'department', key: 'dept' },
    { title: '区域', dataIndex: 'region', key: 'region' },
    { title: '状态', dataIndex: 'is_active', key: 'active', render: (v: number) =>
      <Tag color={v ? 'green' : 'red'}>{v ? '活跃' : '禁用'}</Tag> },
  ];

  const logColumns = [
    { title: '用户', dataIndex: 'username', key: 'user', width: 100 },
    { title: '查询', dataIndex: 'original_query', key: 'query', ellipsis: true },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <Tag color={v === 'success' ? 'green' : 'red'}>{v}</Tag> },
    { title: '耗时', dataIndex: 'exec_time_ms', key: 'time', width: 80,
      render: (v: number) => `${v?.toFixed(0) || 0}ms` },
    { title: '时间', dataIndex: 'created_at', key: 'at', width: 160 },
  ];

  const items = [
    {
      key: 'stats', label: '系统统计',
      children: loading ? <Spin /> : (
        <Row gutter={[16, 16]}>
          <Col span={6}><Card><Statistic title="总查询数" value={stats?.total_queries || 0} /></Card></Col>
          <Col span={6}><Card><Statistic title="活跃用户" value={stats?.unique_users || 0} /></Card></Col>
          <Col span={6}><Card><Statistic title="准确率" value={stats?.accuracy || 0} suffix="%" precision={1} /></Card></Col>
          <Col span={6}><Card><Statistic title="平均延迟" value={stats?.avg_latency_ms || 0} suffix="ms" precision={0} /></Card></Col>
        </Row>
      ),
    },
    {
      key: 'users', label: '用户管理',
      children: <Table dataSource={users} columns={userColumns} rowKey="user_id" size="small" loading={loading} />,
    },
    {
      key: 'logs', label: '查询日志',
      children: <Table dataSource={logs} columns={logColumns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 15, showSizeChanger: true }} />,
    },
  ];

  return (
    <div>
      <Title level={4}>⚙️ 系统管理</Title>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} />
    </div>
  );
}
