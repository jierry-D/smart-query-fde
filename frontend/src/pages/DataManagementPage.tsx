import { useState, useEffect } from 'react';
import { Table, Spin, Typography, Card, Upload, Button, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import type { SnapshotItem } from '@/types';
import client from '@/api/client';

const { Title, Text } = Typography;

export default function DataManagementPage() {
  const [snapshots, setSnapshots] = useState<SnapshotItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    client.get('/snapshots').then(({ data }) => {
      setSnapshots(data.snapshots || []);
    }).finally(() => setLoading(false));
  }, []);

  const columns = [
    { title: 'ID', dataIndex: 'snapshot_id', key: 'id', width: 60 },
    { title: '数据表', dataIndex: 'table_name', key: 'table', width: 160,
      render: (v: string) => <Text code>{v}</Text> },
    { title: '数据期间', dataIndex: 'data_period', key: 'period', width: 120,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '录入时间', dataIndex: 'ingestion_time', key: 'time', width: 180 },
    { title: '描述', dataIndex: 'description', key: 'desc' },
  ];

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>;

  return (
    <div>
      <Title level={4}>📦 数据管理</Title>
      <Card size="small" style={{ marginBottom: 16, background: '#fafafa' }}>
        <Text type="secondary">当前共 {snapshots.length} 个数据快照</Text>
      </Card>
      <Table
        dataSource={snapshots}
        columns={columns}
        rowKey="snapshot_id"
        size="middle"
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
