import { useState, useEffect } from 'react';
import { Table, Spin, Typography, Card, Upload, Button, message, Alert, Space } from 'antd';
import { UploadOutlined, ReloadOutlined } from '@ant-design/icons';
import type { SnapshotItem } from '@/types';
import client from '@/api/client';

const { Title, Text } = Typography;

export default function DataManagementPage() {
  const [snapshots, setSnapshots] = useState<SnapshotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);

  const loadSnapshots = () => {
    setLoading(true);
    client.get('/snapshots').then(({ data }) => {
      setSnapshots(data.snapshots || []);
    }).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { loadSnapshots(); }, []);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setImportResult(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const { data } = await client.post('/import', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setImportResult(data);
      if (data.total_imported > 0) {
        message.success(`成功导入 ${data.total_imported} 个工作表`);
      }
      loadSnapshots();
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || '导入失败';
      message.error(msg);
      setImportResult({ error: msg });
    }
    setUploading(false);
    return false;
  };

  const columns = [
    { title: 'ID', dataIndex: 'snapshot_id', key: 'id', width: 60 },
    { title: '数据表', dataIndex: 'table_name', key: 'table', width: 160,
      render: (v: string) => <Text code>{v}</Text> },
    { title: '数据期间', dataIndex: 'data_period', key: 'period', width: 120,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '录入时间', dataIndex: 'ingestion_time', key: 'time', width: 180 },
    { title: '描述', dataIndex: 'description', key: 'desc' },
  ];

  const importColumns = [
    { title: '工作表', dataIndex: 'sheet', key: 'sheet' },
    { title: '数据表', dataIndex: 'table_name', key: 'table' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => v === 'imported'
        ? <Text type="success">✅ 已导入</Text>
        : <Text type="secondary">⏭ 跳过</Text> },
    { title: '行数', dataIndex: 'row_count', key: 'rows', width: 80 },
    { title: '说明', dataIndex: 'reason', key: 'reason' },
  ];

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>;

  return (
    <div>
      <Title level={4}>📦 数据管理</Title>

      <Card size="small" title="📥 导入 Excel 数据" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text type="secondary">支持 .xlsx 文件，自动识别表头和列类型，去重检测</Text>
          <Upload
            accept=".xlsx,.xls"
            showUploadList={false}
            beforeUpload={handleUpload}
            disabled={uploading}
          >
            <Button icon={<UploadOutlined />} loading={uploading} type="primary">
              {uploading ? '导入中...' : '选择 Excel 文件'}
            </Button>
          </Upload>
        </Space>
        {importResult && !importResult.error && (
          <Table
            style={{ marginTop: 12 }}
            dataSource={importResult.sheets || []}
            columns={importColumns}
            rowKey="sheet"
            size="small"
            pagination={false}
            locale={{ emptyText: '无导入结果' }}
          />
        )}
        {importResult?.error && (
          <Alert type="error" message={importResult.error} style={{ marginTop: 12 }} showIcon />
        )}
        {importResult && !importResult.error && importResult.total_imported === 0 && (
          <Alert type="info" message="所有工作表已存在，无需重复导入" style={{ marginTop: 12 }} showIcon />
        )}
      </Card>

      <Card size="small" title={<Space><Text>📋 数据快照</Text><Button size="small" icon={<ReloadOutlined />} onClick={loadSnapshots} /></Space>}>
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
