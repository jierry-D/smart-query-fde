import { useState, useEffect } from 'react';
import { Table, Tag, Input, Spin, Typography, Card } from 'antd';
import type { MetricItem } from '@/types';
import client from '@/api/client';

const { Text, Title } = Typography;

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  useEffect(() => {
    client.get('/metrics').then(({ data }) => {
      setMetrics(data.metrics || []);
    }).finally(() => setLoading(false));
  }, []);

  const filtered = search
    ? metrics.filter(m => m.name.includes(search) || m.category.includes(search))
    : metrics;

  const columns = [
    { title: '指标名称', dataIndex: 'name', key: 'name', width: 280,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '分类', dataIndex: 'category', key: 'category', width: 120,
      render: (v: string) => <Tag>{v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => <Tag color={v === 'available' ? 'green' : 'orange'}>{v === 'available' ? '可用' : '待配置'}</Tag> },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 80 },
    { title: '说明', dataIndex: 'description', key: 'description' },
  ];

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>📋 指标目录</Title>
        <Input.Search
          placeholder="搜索指标..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 280 }}
          allowClear
        />
      </div>
      <Table
        dataSource={filtered}
        columns={columns}
        rowKey="id"
        size="middle"
        pagination={{ pageSize: 20, showSizeChanger: true, showTotal: t => `共 ${t} 个指标` }}
      />
    </div>
  );
}
