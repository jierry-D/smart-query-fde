import { useState, useEffect } from 'react';
import { Row, Col, Card, Statistic, Spin } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import client from '@/api/client';

interface DashboardData {
  total_bid: number;
  total_contract: number;
  total_opportunity: number;
  total_receivable: number;
  city_distribution: { label: string; value: number }[];
  business_line_distribution: { label: string; value: number }[];
}

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => { loadDashboard(); }, []);

  const loadDashboard = async () => {
    try {
      const { data: d } = await client.get('/dashboard');
      setData(d);
    } catch (e) {
      // Try individual queries
      try {
        const [bid, contract, opp, recv] = await Promise.all([
          client.post('/chat', { q: '年度累计中标总额' }),
          client.post('/chat', { q: '年度累计签约总额' }),
          client.post('/chat', { q: '商机总金额' }),
          client.post('/chat', { q: '应收账款总额' }),
        ]);
        setData({
          total_bid: bid.data.value || 0,
          total_contract: contract.data.value || 0,
          total_opportunity: opp.data.value || 0,
          total_receivable: recv.data.value || 0,
          city_distribution: [],
          business_line_distribution: [],
        });
      } catch { /* init_db not run */ }
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;

  const cityOpt = {
    tooltip: { trigger: 'axis' },
    grid: { left: 100, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: (data?.city_distribution || []).map(d => d.label).reverse(), inverse: true },
    series: [{
      type: 'bar', data: (data?.city_distribution || []).map(d => d.value).reverse(),
      itemStyle: { color: '#4f46e5', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 24,
    }],
  };

  const bizLineOpt = {
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie', radius: ['45%', '70%'],
      data: (data?.business_line_distribution || []).map(d => ({ name: d.label, value: d.value })),
      label: { show: true, formatter: '{b}\n{d}%' },
      itemStyle: { borderRadius: 4 },
    }],
  };

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>📊 经营仪表盘</h2>
      <Row gutter={[16, 16]}>
        <Col xs={12} sm={6}>
          <Card><Statistic title="年度中标总额" value={data?.total_bid || 0} suffix="万元" prefix="💰" /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="年度签约总额" value={data?.total_contract || 0} suffix="万元" prefix="📝" /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="商机总额" value={data?.total_opportunity || 0} suffix="万元" prefix="🎯" /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="应收账款" value={data?.total_receivable || 0} suffix="万元" prefix="📋"
            valueStyle={{ color: (data?.total_receivable || 0) > 1000 ? '#cf1322' : undefined }} /></Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={14}>
          <Card title="各地市中标分布"><ReactECharts option={cityOpt} style={{ height: 350 }} /></Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="业务线分布"><ReactECharts option={bizLineOpt} style={{ height: 350 }} /></Card>
        </Col>
      </Row>
    </div>
  );
}
