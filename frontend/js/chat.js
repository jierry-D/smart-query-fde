/* 智慧问数系统 v2.0 */

function rotatePlaceholder() {
  const inp = document.getElementById('queryInput');
  if (!inp || document.activeElement === inp) return; // 用户正在输入时不轮换
  inp.placeholder = GUIDANCE_PLACEHOLDERS[placeholderIdx];
  placeholderIdx = (placeholderIdx + 1) % GUIDANCE_PLACEHOLDERS.length;
}
function getRecentQueries() {
  try { return JSON.parse(localStorage.getItem('sq2_recent') || '[]'); } catch(e) { return []; }
}
function addRecentQuery(q) {
  let recent = getRecentQueries();
  recent = [q, ...recent.filter(r => r !== q)].slice(0, 10);
  localStorage.setItem('sq2_recent', JSON.stringify(recent));
}
function newChat() {
  switchView('chatView'); setActiveNav('navChat'); loadHistoryPanel();
  // 显示欢迎信息和最近查询
  const msgs = gid('chatMessages');
  const recent = getRecentQueries();
  let recentHtml = '';
  if (recent.length > 0) {
    recentHtml = '<div style="margin-top:16px"><div style="font-size:.8rem;color:var(--c-text-secondary);margin-bottom:8px">🕐 最近查询</div>';
    recent.slice(0, 5).forEach(q => {
      recentHtml += `<button class="clarify-opt" style="margin:2px 4px" onclick="quickQuery('${esc(q)}')">${esc(q)}</button>`;
    });
    recentHtml += '</div>';
  }
  msgs.innerHTML = `<div class="welcome-msg">
    <div class="welcome-big">🤖</div>
    <h2>智慧问数系统 v2.0</h2>
    <p>用自然语言查询企业数据 — 试试下面的示例或直接输入问题</p>
    <div class="quick-actions">
      <button onclick="quickQuery('Q3 年度累计中标总额')">📊 Q3中标总额</button>
      <button onclick="quickQuery('本月 南宁市 本期签约额')">📋 本月南宁签约</button>
      <button onclick="quickQuery('Top 10 各地市中标额')">🏆 各地市排名</button>
      <button onclick="quickQuery('各业务线中标金额占比')">📈 业务线分布</button>
      <button onclick="quickQuery('同比 商机签约转化率')">📉 同比转化率</button>
      <button onclick="quickQuery('/list')">📋 查看所有指标</button>
    </div>
    ${recentHtml}
  </div>`;
}
async function doQuery() {
  const inp = gid('queryInput'); const q = inp.value.trim(); if (!q) return; inp.value = '';
  if (!token) { showLogin(); return; }

  const msgs = gid('chatMessages');
  // Remove welcome
  const w = msgs.querySelector('.welcome-msg'); if (w) w.remove();

  // User bubble
  const uid = ++msgId;
  msgs.appendChild(htmlToEl(`<div class="msg-bubble msg-user" id="msg-${uid}"><div class="msg-content">${esc(q)}</div><div class="msg-meta">${timeNow()}</div></div>`));

  // Loading
  const lid = ++msgId;
  msgs.appendChild(htmlToEl(`<div class="msg-bubble msg-ai" id="msg-${lid}"><div class="msg-content"><div class="loading-spinner"><div class="spinner"></div>查询中...</div></div></div>`));
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const d = await api('/api/chat', { method: 'POST', body: JSON.stringify({ q }) });
    const el = gid('msg-' + lid);
    if (el) el.innerHTML = renderResponse(d);
    addRecentQuery(q);
  } catch(e) {
    const el = gid('msg-' + lid);
    if (el) el.innerHTML = `<div class="msg-content"><div class="error-box"><div class="err-title">查询失败</div>${esc(e.message)}</div></div>`;
  }
  msgs.scrollTop = msgs.scrollHeight;
  loadStatus();
}
function quickQuery(q) {
  gid('queryInput').value = q; doQuery();
}
function renderResponse(d) {
  const type = d.type || 'error';
  let html = '<div class="msg-content">';

  switch (type) {
    case 'number': html += renderNumber(d); break;
    case 'table': html += renderTable(d); break;
    case 'error': html += renderError(d); break;
    case 'pending': html += renderPending(d); break;
    case 'clarify': html += renderClarify(d); break;
    case 'metric_list': html += renderMetricsList(d); break;
    case 'snapshot_list': html += renderSnapshotsList(d); break;
    case 'db_status': html += renderDbStatus(d); break;
    case 'help': html += `<pre style="font-size:.82rem;line-height:1.6">${esc(d.text)}</pre>`; break;
    case 'metric_detail': html += renderMetricDetail(d); break;
    case 'import_result': html += renderImportResult(d); break;
    default: html += `<pre style="font-size:.75rem">${esc(JSON.stringify(d,null,2))}</pre>`;
  }

  // Preflight warnings (Stage 0)
  if (d.preflight && d.preflight.messages && d.preflight.messages.length) {
    const pStatus = d.preflight.status;
    const pIcon = pStatus === 'error' ? '❌' : pStatus === 'warning' ? '⚠️' : 'ℹ️';
    const pClass = pStatus === 'error' ? 'preflight-err' : pStatus === 'warning' ? 'preflight-warn' : 'preflight-ok';
    html += `<div class="preflight-box ${pClass}"><strong>${pIcon} 数据预检</strong><ul style="margin:4px 0 0 16px;font-size:.78rem">`;
    d.preflight.messages.forEach(m => html += `<li>${esc(m)}</li>`);
    html += '</ul></div>';
  }

  // Process stages — always visible for transparency
  if (d.process && d.process.length) {
    html += `<div class="process-details">
      <div class="process-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
        🔍 查询过程 · ${d.elapsed_ms||'?'}ms
      </div>
      <div class="stage-list">`;
    d.process.forEach(s => {
      const icon = s.status === 'done' ? '✅' : s.status === 'error' ? '❌' : '⏳';
      const cls = s.status === 'done' ? 'stage-ok' : s.status === 'error' ? 'stage-err' : '';
      html += `<div class="stage-item ${cls}"><span class="stage-icon">${icon}</span><span class="stage-name">${s.name}</span><span class="stage-detail">${esc(s.detail||'')}</span><span class="stage-time">${s.elapsed_ms}ms</span></div>`;
    });
    html += '</div></div>';
  }

  // SQL details
  if (d.sql) {
    html += `<details style="margin-top:8px"><summary style="font-size:.72rem;cursor:pointer;color:var(--c-text-secondary)">📝 SQL</summary><pre style="font-size:.68rem;background:#1e293b;color:#e2e8f0;padding:8px;border-radius:6px;overflow-x:auto;margin-top:4px">${esc(d.sql)}</pre></details>`;
  }

  // Time intelligence
  if (d.time_intelligence && d.time_intelligence.available) {
    const ti = d.time_intelligence;
    const color = ti.growth_rate >= 0 ? 'var(--c-success)' : 'var(--c-danger)';
    html += `<div style="margin-top:8px;font-size:.82rem;padding:8px 12px;background:#f8fafc;border-radius:6px">
      <strong>${ti.label}:</strong> ${(ti.previous_value||0).toLocaleString()} → ${(ti.current_value||0).toLocaleString()}
      <span style="color:${color};font-weight:700">${ti.growth_rate >= 0 ? '↑' : '↓'} ${Math.abs(ti.growth_rate||0)}%</span>
    </div>`;
  }

  // Feedback buttons
  const qid = d._qid || '';
  html += `<div class="feedback-row" data-qid="${esc(qid)}" data-query="${esc(d._query||'')}">
    <span class="feedback-label">这个结果有帮助吗？</span>
    <button class="fb-btn" onclick="sendFeedback(this, 'up')" title="有用">👍</button>
    <button class="fb-btn" onclick="sendFeedback(this, 'down')" title="没用">👎</button>
    <span class="fb-thanks" style="display:none">感谢反馈!</span>
  </div>`;

  html += `<div class="msg-meta">${timeNow()} | 🔒 ${esc(d.data_scope||'')}</div></div>`;
  return html;
}
async function sendFeedback(btn, rating) {
  const row = btn.closest('.feedback-row');
  const query = row.dataset.query || '';
  const thanks = row.querySelector('.fb-thanks');

  // Visual feedback
  row.querySelectorAll('.fb-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  try {
    await api('/api/feedback', {
      method: 'POST',
      body: JSON.stringify({ rating, comment: '', original_query: query }),
    });
    thanks.style.display = 'inline';
  } catch(e) {
    // Silent fail - feedback is non-critical
  }
}
function renderNumber(d) {
  let cls = 'stat-number';
  if (d.alert_level === '紧急') cls += ' danger';
  else if (d.alert_level === '重要') cls += ' warning';
  else if (d.alert_level === '一般') cls += ' info-alert';
  else if (d.alert_level === '提示') cls += ' tip-alert';

  // Alert badge
  let alertBadge = '';
  if (d.alert_level) {
    const alertIcons = { '紧急': '🔴', '重要': '🔶', '一般': '🟡', '提示': '🔵' };
    alertBadge = `<span class="alert-badge alert-${d.alert_level}">${alertIcons[d.alert_level]||''} ${d.alert_level}</span>`;
  }

  let h = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="font-size:.8rem;color:var(--c-text-secondary)">${esc(d.display_name||d.metric_name)}</span>${alertBadge}</div>`;
  h += `<div class="${cls}">${d.value != null ? d.value.toLocaleString() : '—'}<span class="stat-unit">${esc(d.unit||'')}</span></div>`;
  // ... rest unchanged

  // Entity tags
  if (d.entity_tags && d.entity_tags.length) {
    h += '<div class="ent-tags">';
    d.entity_tags.forEach(t => h += `<span class="ent-tag ${t.type}">${esc(t.label)}</span>`);
    h += '</div>';
  }

  // Explanation + Formula
  if (d.explanation) h += `<div class="metric-explain">📖 ${esc(d.explanation)}</div>`;
  if (d.formula) h += `<div class="metric-formula">📐 ${esc(d.formula)}</div>`;

  // Trend analysis
  if (d.time_intelligence && d.time_intelligence.available) {
    const ti = d.time_intelligence;
    const color = ti.growth_rate >= 0 ? 'var(--c-success)' : 'var(--c-danger)';
    const arrow = ti.growth_rate >= 0 ? '↑' : '↓';
    h += `<div class="trend-box" style="border-left-color:${color}">
      <div class="trend-title">📈 ${ti.label || '变化趋势'}</div>
      <div class="trend-values">
        <span>上期: ${(ti.previous_value||0).toLocaleString()}</span>
        <span class="trend-arrow">→</span>
        <span>本期: ${(ti.current_value||d.value||0).toLocaleString()}</span>
        <span class="trend-rate" style="color:${color}">${arrow} ${Math.abs(ti.growth_rate||0).toFixed(1)}%</span>
      </div>
    </div>`;
  }

  return h;
}
function renderTable(d) {
  let alertBadge = '';
  if (d.alert_level) {
    const alertIcons = { '紧急': '🔴', '重要': '🔶', '一般': '🟡', '提示': '🔵' };
    alertBadge = `<span class="alert-badge alert-${d.alert_level}">${alertIcons[d.alert_level]||''} ${d.alert_level}</span>`;
  }
  let h = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="font-size:.8rem;color:var(--c-text-secondary)">${esc(d.display_name||d.metric_name)} <span style="margin-left:8px">${d.row_count||0} 行</span></span>${alertBadge}</div>`;

  if (d.entity_tags && d.entity_tags.length) {
    h += '<div class="ent-tags">';
    d.entity_tags.forEach(t => h += `<span class="ent-tag ${t.type}">${esc(t.label)}</span>`);
    h += '</div>';
  }

  if (d.rows && d.rows.length) {
    h += '<table class="data-table"><thead><tr>';
    const cols = d.columns || Object.keys(d.rows[0]);
    cols.forEach(c => h += `<th>${esc(c)}</th>`);
    h += '</tr></thead><tbody>';
    d.rows.forEach(row => {
      h += '<tr>';
      cols.forEach(c => { const v = row[c]; h += `<td>${v != null ? (typeof v === 'number' ? v.toLocaleString() : esc(String(v))) : ''}</td>`; });
      h += '</tr>';
    });
    h += '</tbody></table>';

    // Explanation for table
    if (d.explanation) h += `<div class="metric-explain">📖 ${esc(d.explanation)}</div>`;

    // CSV export button
    if (d._query) {
      h += `<div style="margin-top:8px">
        <button class="btn-sm" style="background:var(--c-success);color:#fff" onclick="exportCSV('${esc(d._query)}')">📥 导出 CSV</button>
      </div>`;
    }

    // Chart for table data (if it's label+value format)
    if (cols.includes('label') && cols.includes('value') && d.rows.length > 1) {
      const cid = 'chart-' + (++msgId);
      h += `<div class="chart-container" id="${cid}"></div>`;
      setTimeout(() => renderBarChart(cid, d.rows), 200);
    }
  } else {
    h += '<div style="font-size:.85rem;color:var(--c-text-secondary);margin-top:8px">暂无数据</div>';
  }
  return h;
}
function renderError(d) {
  let h = `<div class="error-box"><div class="err-title">❌ ${esc(d.message)}</div>`;
  if (d.suggestions && d.suggestions.length) {
    h += '<div class="err-hints">';
    d.suggestions.forEach(s => h += `<span class="err-hint" onclick="quickQuery('${esc(s)}')">${esc(s)}</span>`);
    h += '</div>';
  }
  h += '</div>';
  return h;
}
function renderPending(d) {
  return `<div style="padding:12px;background:#fffbeb;border-left:4px solid var(--c-warning);border-radius:0 8px 8px 0">
    <div style="font-weight:600;color:var(--c-warning)">⚠️ ${esc(d.metric_name)}</div>
    <div style="font-size:.8rem;color:var(--c-text-secondary);margin-top:4px">${esc(d.hint||d.explanation||'该指标数据尚未接入')}</div>
  </div>`;
}
function renderClarify(d) {
  let h = `<div style="padding:12px 16px;background:#eef2ff;border-left:4px solid var(--c-primary);border-radius:0 8px 8px 0">
    <div style="font-weight:600;color:var(--c-primary);margin-bottom:8px">💡 ${esc(d.question)}</div>`;
  (d.options||[]).forEach(o => {
    const icon = o.action === 'command' ? '📋' : o.action === 'refine' ? '🔍' : '';
    h += `<button class="clarify-opt" data-action="${esc(o.action)}" data-value="${esc(o.value)}">${icon} ${esc(o.label)}</button> `;
  });
  if (d.hint) h += `<div style="font-size:.75rem;color:var(--c-text-secondary);margin-top:8px">${esc(d.hint)}</div>`;
  h += '</div>';
  return h;
}
function renderMetricsList(d) {
  let h = `<h3 style="margin-bottom:12px">📋 指标目录 (${d.total||0} 个, ${d.available||0} 可用)</h3>`;
  const cats = {};
  (d.metrics||[]).forEach(m => { const c = m.category||'其他'; if (!cats[c]) cats[c] = []; cats[c].push(m); });
  Object.entries(cats).forEach(([cat, items]) => {
    h += `<div class="metric-category"><h3>${esc(cat)} (${items.length})</h3>`;
    items.forEach(m => {
      const icon = m.status === 'available' ? '✅' : '⏳';
      h += `<div class="metric-item" onclick="quickQuery('${esc(m.name)}')">
        <span class="metric-name">${icon} ${esc(m.name)}</span>
        <span class="metric-meta">${esc(m.complexity||'')} <span class="metric-badge">${m.result_format||''}</span></span>
      </div>`;
    });
    h += '</div>';
  });
  return h;
}
function renderSnapshotsList(d) {
  let h = `<h3 style="margin-bottom:12px">📦 数据快照 (${d.total||0} 个)</h3>`;
  h += '<table class="data-table"><thead><tr><th>ID</th><th>表名</th><th>数据期间</th><th>行数</th><th>描述</th></tr></thead><tbody>';
  (d.snapshots||[]).forEach(s => {
    const isNew = s.snapshot_id === d.latest_id;
    h += `<tr${isNew ? ' style="background:#f0fdf4"' : ''}><td>${s.snapshot_id}${isNew?' ⭐':''}</td><td>${esc(s.table_name)}</td><td>${esc(s.data_period)}</td><td>${s.total_rows||0}</td><td>${esc(s.description||'')}</td></tr>`;
  });
  h += '</tbody></table>';
  return h;
}
function renderDbStatus(d) {
  let h = `<h3 style="margin-bottom:12px">🗄️ 数据库</h3>`;
  h += '<table class="data-table"><thead><tr><th>表名</th><th>行数</th></tr></thead><tbody>';
  (d.tables||[]).forEach(t => h += `<tr><td>${esc(t.table_name)}</td><td>${(t.row_count||0).toLocaleString()}</td></tr>`);
  h += '</tbody></table>';
  return h;
}
function renderMetricDetail(d) {
  let h = `<h3 style="margin-bottom:8px">${esc(d.name)}</h3>`;
  h += '<table class="data-table">';
  ['metric_id','category','status','complexity','explanation','formula','source','result_format','result_unit'].forEach(k => {
    if (d[k]) h += `<tr><td style="font-weight:600;width:80px">${k}</td><td>${esc(String(d[k]))}</td></tr>`;
  });
  h += '</table>';
  if (d.sql_template) h += `<pre style="font-size:.72rem;background:#1e293b;color:#e2e8f0;padding:8px;border-radius:6px;margin-top:8px;overflow-x:auto">${esc(d.sql_template)}</pre>`;
  return h;
}
function renderImportResult(d) {
  let h = `<h3 style="margin-bottom:12px">📤 导入结果 (✅ ${d.total_imported||0} | ⚠️ ${d.total_skipped||0})</h3>`;
  h += '<table class="data-table"><thead><tr><th>Sheet</th><th>状态</th><th>表名</th><th>期间</th><th>行数</th><th>说明</th></tr></thead><tbody>';
  (d.sheets||[]).forEach(s => {
    h += `<tr><td>${esc(s.sheet)}</td><td>${s.status==='imported'?'✅':'⚠️'} ${s.status}</td><td>${esc(s.table_name||'')}</td><td>${esc(s.data_period||'')}</td><td>${s.row_count||''}</td><td>${esc(s.reason||'')}</td></tr>`;
  });
  h += '</tbody></table>';
  return h;
}
function renderBarChart(cid, rows) {
  const el = document.getElementById(cid); if (!el) return;
  const chart = echarts.init(el);
  const labels = rows.slice(0, 20).map(r => r.label).reverse();
  const values = rows.slice(0, 20).map(r => r.value).reverse();
  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 100, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: labels, axisLabel: { fontSize: 11 } },
    series: [{ type: 'bar', data: values, itemStyle: { color: '#4f46e5', borderRadius: [0,4,4,0] }, barMaxWidth: 24 }]
  });
  setTimeout(() => chart.resize(), 100);
  window.addEventListener('resize', () => chart.resize());
}
async function loadHistoryPanel() {
  const panel = gid('historyPanel');
  if (!panel) return;
  try {
    const d = await api('/api/history?limit=15');
    if (!d.logs || !d.logs.length) {
      panel.innerHTML = '<div style="padding:12px;font-size:.78rem;color:var(--c-text-secondary)">暂无查询记录</div>';
      return;
    }
    let h = '';
    d.logs.forEach(l => {
      const statusIcon = l.status === 'success' ? '✅' : '❌';
      h += `<div class="history-item" onclick="quickQuery('${esc(l.original_query||'')}')" title="${esc(l.original_query||'')}">
        <span>${statusIcon}</span>
        <span class="history-query">${esc((l.original_query||'').slice(0,30))}</span>
        <span class="history-time">${(l.created_at||'').slice(5,16)}</span>
      </div>`;
    });
    panel.innerHTML = h;
  } catch(e) {
    // silent
  }
}
function toggleHistory() {
  const panel = gid('historyPanel');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) loadHistoryPanel();
}
function exportCSV(query) {
  const a = document.createElement('a');
  a.href = '/api/export/csv';
  a.download = '';
  // Use a form POST to trigger download with auth
  fetch('/api/export/csv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ q: query }),
  }).then(r => r.blob()).then(blob => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `query_result_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  });
}

// ── Event delegation for clarify buttons ──
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.clarify-opt');
  if (!btn) return;
  const action = btn.dataset.action;
  const value = btn.dataset.value;
  if (action === 'refine') { gid('queryInput').value = value; doQuery(); }
  else if (action === 'command') { gid('queryInput').value = value; doQuery(); }
});
