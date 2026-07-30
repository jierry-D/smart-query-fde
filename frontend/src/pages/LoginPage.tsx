import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, Card, Typography, message, Tag, Space } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuthStore } from '@/stores/authStore';

const { Title, Text } = Typography;

const TEST_ACCOUNTS = [
  { role: '管理员', tag: 'admin', user: 'admin', pass: 'admin123', hint: '全部数据' },
  { role: '领导', tag: 'leader', user: 'leader', pass: 'leader123', hint: '部门数据' },
  { role: '员工', tag: 'employee', user: 'employee', pass: 'emp123', hint: '个人数据' },
];

const TAG_COLORS: Record<string, string> = { admin: 'red', leader: 'blue', employee: 'green' };

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const { login, token } = useAuthStore();
  const navigate = useNavigate();

  if (token) {
    navigate('/dashboard', { replace: true });
    return null;
  }

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(values.username, values.password);
      message.success('登录成功');
      navigate('/dashboard', { replace: true });
    } catch (e: any) {
      message.error(e.response?.data?.detail || '登录失败，请检查用户名密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      height: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    }}>
      <Card style={{ width: 420, borderRadius: 12, boxShadow: '0 8px 24px rgba(0,0,0,.15)' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🔍</div>
          <Title level={3} style={{ marginBottom: 4 }}>智慧问数系统</Title>
          <Text type="secondary">企业级 NL2SQL 智能数据查询平台</Text>
        </div>

        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="admin / leader / employee" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登 录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>测试账号：</Text>
          {TEST_ACCOUNTS.map(a => (
            <div key={a.user} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, fontSize: 12 }}>
              <Tag color={TAG_COLORS[a.tag]} style={{ margin: 0 }}>{a.role}</Tag>
              <code style={{ fontSize: 12 }}>{a.user}</code>
              <Text type="secondary">/ {a.pass}</Text>
              <Text type="secondary" style={{ fontSize: 11 }}>({a.hint})</Text>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
