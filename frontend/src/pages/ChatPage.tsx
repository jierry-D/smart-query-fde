import { useState, useRef, useEffect } from 'react';
import { Input, Button, Card, Tag, Space, Collapse, Spin, Empty, Typography, message } from 'antd';
import { SendOutlined, LikeOutlined, DislikeOutlined, ReloadOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
// react-markdown not available — using plain text rendering
import client from '@/api/client';
import type { ChatResponse } from '@/types';

const { Text } = Typography;

interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  response?: ChatResponse;
  process?: any[];
  loading?: boolean;
  streamingStages?: any[];
}

const QUICK_QUERIES = [
  'Q3 年度累计中标总额', '本月 本期签约额', '南宁市 中标总额',
  'Top 5 各地市中标额', '同比 商机签约转化率', '逾期90天以上应收款',
];

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);

  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const doQuery = async (q: string) => {
    if (!q.trim() || loading) return;
    setInput('');
    setLoading(true);

    const userMsg: ChatMessage = { id: Date.now(), role: 'user', content: q };
    const assistantMsg: ChatMessage = { id: Date.now() + 1, role: 'assistant', content: '', loading: true,
      process: [] as any[], streamingStages: [] as any[] };
    setMessages(prev => [...prev, userMsg, assistantMsg]);

    const token = localStorage.getItem('sq2_token');

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ q }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: '请求失败' }));
        throw new Error(err.detail);
      }

      const contentType = response.headers.get('content-type') || '';

      if (contentType.includes('text/event-stream')) {
        // SSE 流式处理
        const reader = response.body?.getReader();
        if (!reader) throw new Error('无法读取流式响应');

        const decoder = new TextDecoder();
        let buf = '';
        let currentStages: any[] = [];

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });

          const lines = buf.split('\n');
          buf = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) { eventType = line.slice(7).trim(); continue; }
            if (!line.startsWith('data: ')) continue;

            try {
              const eventData = JSON.parse(line.slice(6));
              if (eventType === 'stage') {
                currentStages = [...currentStages, eventData];
                setMessages(prev => prev.map(m =>
                  m.id === assistantMsg.id ? { ...m, streamingStages: currentStages } : m
                ));
              } else if (eventType === 'result') {
                setMessages(prev => prev.map(m =>
                  m.id === assistantMsg.id
                    ? { ...m, response: eventData, process: currentStages, streamingStages: [], loading: false, content: formatResponse(eventData) }
                    : m
                ));
              } else if (eventType === 'error') {
                setMessages(prev => prev.map(m =>
                  m.id === assistantMsg.id
                    ? { ...m, response: { type: 'error', message: eventData?.message }, loading: false, content: '❌ 查询失败' }
                    : m
                ));
              }
            } catch { /* skip parse errors */ }
          }
        }
      } else {
        // JSON 响应
        const data = await response.json();
        setMessages(prev => prev.map(m =>
          m.id === assistantMsg.id
            ? { ...m, response: data, process: data.process, loading: false, content: formatResponse(data) }
            : m
        ));
      }
    } catch (e: any) {
      setMessages(prev => prev.map(m =>
        m.id === assistantMsg.id
          ? { ...m, response: { type: 'error', message: e.message || '查询失败' }, loading: false, content: '❌ 查询失败' }
          : m
      ));
    } finally {
      setLoading(false);
    }
  };

  const sendFeedback = async (_msgId: number, rating: 'up' | 'down') => {
    try {
      await client.post('/feedback', { rating });
      message.success('感谢反馈！');
    } catch { message.error('反馈失败'); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <h2 style={{ marginBottom: 16 }}>💬 智能问数</h2>

      {/* Messages Area */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 4px' }}>
        {messages.length === 0 ? (
          <Empty description="输入自然语言查询企业数据" style={{ marginTop: 60 }}>
            <Space wrap>
              {QUICK_QUERIES.map(q => (
                <Button key={q} onClick={() => doQuery(q)} size="small">{q}</Button>
              ))}
            </Space>
          </Empty>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className="msg-enter" style={{ marginBottom: 16 }}>
              {msg.role === 'user' ? (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <div style={{
                    background: '#4f46e5', color: '#fff', padding: '8px 16px',
                    borderRadius: '12px 12px 0 12px', maxWidth: '70%',
                  }}>
                    {msg.content}
                  </div>
                </div>
              ) : (
                <Card size="small" style={{ maxWidth: '90%' }}>
                  {msg.loading ? (
                    <div>
                      <Spin tip="查询中..." />
                      {msg.streamingStages && msg.streamingStages.length > 0 && (
                        <div style={{ marginTop: 12, fontSize: 12 }}>
                          {msg.streamingStages.map((s: any, i: number) => (
                            <div key={i} style={{ color: '#8c8c8c', marginBottom: 2 }}>
                              <Tag color={s.status === 'done' ? 'green' : 'blue'} style={{ fontSize: 10 }}>
                                {s.status === 'done' ? '✓' : '⋯'}
                              </Tag>
                              {s.name} ({s.elapsed_ms}ms)
                              {s.detail && <span style={{ color: '#bfbfbf' }}> — {s.detail}</span>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : msg.response ? (
                    <RenderResponse response={msg.response} />
                  ) : null}

                  {/* Process Panel */}
                  {msg.process && msg.process.length > 0 && (
                    <Collapse ghost style={{ marginTop: 8 }} items={[{
                      key: 'process', label: <Text type="secondary" style={{ fontSize: 12 }}>📋 查询过程</Text>,
                      children: msg.process.map((s: any, i: number) => (
                        <div key={i} style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>
                          <Tag color={s.status === 'done' ? 'green' : s.status === 'error' ? 'red' : 'blue'} style={{ fontSize: 10 }}>
                            {s.status === 'done' ? '✓' : s.status === 'error' ? '✗' : '⋯'}
                          </Tag>
                          {s.name} ({s.elapsed_ms}ms) {s.detail && `— ${s.detail}`}
                        </div>
                      )),
                    }]} />
                  )}

                  {/* Feedback */}
                  {msg.response && msg.response.type !== 'error' && (
                    <Space style={{ marginTop: 8 }}>
                      <Button size="small" icon={<LikeOutlined />} type="text" onClick={() => sendFeedback(msg.id, 'up')} />
                      <Button size="small" icon={<DislikeOutlined />} type="text" onClick={() => sendFeedback(msg.id, 'down')} />
                    </Space>
                  )}
                </Card>
              )}
            </div>
          ))
        )}
        <div ref={messagesEnd} />
      </div>

      {/* Input */}
      <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
        <Input
          size="large"
          value={input}
          onChange={e => setInput(e.target.value)}
          onPressEnter={() => doQuery(input)}
          placeholder="输入自然语言查询... 例如: Q3 年度累计中标总额"
          disabled={loading}
        />
        <Button type="primary" size="large" icon={<SendOutlined />} onClick={() => doQuery(input)} loading={loading}>
          查询
        </Button>
      </div>
    </div>
  );
}

/* Response Renderer */
function RenderResponse({ response }: { response: ChatResponse }) {
  const { type, metric_name, value, unit, explanation, formula, sql, columns, rows } = response;

  switch (type) {
    case 'number':
      return (
        <div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#4f46e5' }}>
            {value?.toLocaleString()} <span style={{ fontSize: 16, color: '#8c8c8c' }}>{unit}</span>
          </div>
          <Text style={{ color: '#8c8c8c' }}>{metric_name}</Text>
          {explanation && <div style={{ marginTop: 8, fontSize: 13, whiteSpace: 'pre-wrap' }}>{explanation}</div>}
          {formula && <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>口径: {formula}</Text>}
          {sql && (
            <Collapse ghost items={[{ key: 'sql', label: <Text type="secondary" style={{ fontSize: 11 }}>查看 SQL</Text>,
              children: <pre style={{ fontSize: 11, background: '#f5f5f5', padding: 8, borderRadius: 4, overflow: 'auto' }}>{sql}</pre>
            }]} />
          )}
        </div>
      );

    case 'table':
      if (!columns || !rows) return <Text type="secondary">无数据</Text>;
      return (
        <div>
          {rows.length > 1 && columns.includes('label') && columns.includes('value') ? (
            <ReactECharts option={{
              tooltip: { trigger: 'axis' },
              grid: { left: 100, right: 20, top: 10, bottom: 20 },
              xAxis: { type: 'value' },
              yAxis: { type: 'category', data: [...rows].map(r => String(r.label)).reverse(), inverse: true },
              series: [{ type: 'bar', data: [...rows].map(r => Number(r.value)).reverse(),
                itemStyle: { color: '#4f46e5', borderRadius: [0, 4, 4, 0] }, barMaxWidth: 24 }],
            }} style={{ height: 280 }} />
          ) : null}
          <div style={{ overflow: 'auto', maxHeight: 300, marginTop: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>{columns.map(c => <th key={c} style={{ textAlign: 'left', padding: '6px 12px', borderBottom: '2px solid #f0f0f0' }}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? '#fafafa' : 'transparent' }}>
                    {columns.map(c => <td key={c} style={{ padding: '4px 12px', borderBottom: '1px solid #f0f0f0' }}>{String(r[c] ?? '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      );

    case 'clarify':
      return (
        <div>
          <Text>请选择：</Text>
          <Space style={{ marginTop: 8 }}>
            {response.clarification?.map((opt, i) => (
              <Button key={i} size="small" onClick={() => {/* trigger re-query */}}>{opt.label}</Button>
            ))}
          </Space>
        </div>
      );

    case 'report':
      return (
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 12, color: '#4f46e5' }}>
            📊 分析报告
          </div>
          {response.sections && (
            <Space wrap style={{ marginBottom: 12 }}>
              {response.sections.map((s, i) => <Tag key={i} color="blue">{s}</Tag>)}
            </Space>
          )}
          {response.queries_executed && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              共执行 {response.queries_executed} 个子查询
            </Text>
          )}
          <div style={{
            background: '#fafafa', padding: 16, borderRadius: 8,
            maxHeight: 500, overflow: 'auto', fontSize: 13,
            lineHeight: 1.8, whiteSpace: 'pre-wrap',
            border: '1px solid #f0f0f0',
          }}>
            {response.report || '报告生成中...'}
          </div>
          {sql && (
            <Collapse ghost items={[{
              key: 'sql', label: <Text type="secondary" style={{ fontSize: 11 }}>查看查询明细</Text>,
              children: <pre style={{ fontSize: 11, background: '#f5f5f5', padding: 8, borderRadius: 4, overflow: 'auto' }}>{sql}</pre>
            }]} />
          )}
        </div>
      );

    case 'error':
      return <Text type="danger">{response.message || '查询出错'}</Text>;

    case 'metric_list':
      return <Text type="secondary">{response.message || '指标列表已加载'}</Text>;

    default:
      return <Text type="secondary">{response.message || '已处理'}</Text>;
  }
}

function formatResponse(r: ChatResponse): string {
  if (r.type === 'number') return `${r.metric_name}: ${r.value?.toLocaleString()} ${r.unit || ''}`;
  if (r.type === 'table') return `表格结果 (${r.rows?.length || 0} 行)`;
  if (r.type === 'report') return `分析报告 (${r.queries_executed || 0} 个子查询)`;
  if (r.type === 'clarify') return '需要进一步明确...';
  if (r.type === 'error') return r.message || '出错';
  return r.message || '';
}

