/* ═══════════════════════════════════════════
   智慧问数系统 v2.0 — 前端应用
   ═══════════════════════════════════════════ */

// ── State ──
let token = null;
let user = null;
let msgId = 0;

// ── Init ──
window.onload = () => {
  const s = localStorage.getItem('sq2');
  if (s) {
    try { const d = JSON.parse(s); token = d.token; user = d.user; } catch(e) {}
  }
  if (token) { showApp(); loadStatus(); } else { showLogin(); }
  setInterval(loadStatus, 60000);
};

// ── API ──
async function api(path, opts = {}) {
  const h = { 'Content-Type': 'application/json', ...opts.headers };
  if (token) h['Authorization'] = `Bearer ${token}`;
  const r = await fetch(path, { ...opts, headers: h });
  if (r.status === 401) { doLogout(); throw new Error('login expired'); }
  if (r.status === 403) { throw new Error('forbidden'); }
  return r.json();
}

// ── Auth ──
async function doLogin() {
  const u = gid('loginUser').value.trim(), p = gid('loginPass').value;
  if (!u || !p) return showLoginErr('请输入用户名和密码');
  try {
    const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }) });
    if (!r.ok) { const e = await r.json(); return showLoginErr(e.detail || '登录失败'); }
    const d = await r.json();
    token = d.access_token; user = d.user;
    localStorage.setItem('sq2', JSON.stringify({ token, user }));
    showApp(); loadStatus(); newChat();
  } catch(e) { showLoginErr('网络错误: ' + e.message); }
}

function doLogout() { token = null; user = null; localStorage.removeItem('sq2'); showLogin(); }

function showLoginErr(m) { const e = gid('loginError'); e.textContent = m; e.style.display = 'block'; }

function showLogin() { gid('loginScreen').style.display = 'flex'; gid('appScreen').style.display = 'none'; }
function showApp() { gid('loginScreen').style.display = 'none'; gid('appScreen').style.display = 'flex'; updateUserUI(); }

function updateUserUI() {
  if (!user) return;
  const maps = { admin: '🔧 管理员', leader: '📊 领导', employee: '👤 员工' };
  gid('userDisplay').innerHTML = `<span class="role-tag ${user.role}">${maps[user.role]||user.role}</span> ${user.display_name || user.username}`;

  // Scope
  const r = user.role;
  let scope = '全部数据';
  if (r === 'leader') scope = (user.department||'全部') + ' (全部区域)';
  else if (r === 'employee') scope = (user.department||'') + ' - ' + (user.region||'');
  gid('dataScope').textContent = '🔒 ' + scope;

  // Role-based nav
  gid('navImport').style.display = (r === 'admin' || r === 'leader') ? '' : 'none';
  gid('navAdmin').style.display = r === 'admin' ? '' : 'none';
}

async function loadStatus() {
  try {
    const d = await api('/api/status');
    gid('statusInfo').innerHTML = `<span>📅 ${d.date}</span><span>📦 ${d.snapshots} 快照</span><span>📋 ${d.metrics_available}/${d.metrics_total} 指标</span>`;
  } catch(e) {}
}

// ── Navigation ──
function newChat() { switchView('chatView'); setActiveNav('navChat'); }
function showMetrics() { switchView('metricsView'); setActiveNav('navMetrics'); loadMetrics(); }
function showSnapshots() { switchView('snapshotsView'); setActiveNav('navSnapshots'); loadSnapshots(); }
function showImport() { switchView('importView'); setActiveNav('navImport'); }
function showAdmin() { switchView('adminView'); setActiveNav('navAdmin'); adminTab('users'); }
function switchView(id) { document.querySelectorAll('.view').forEach(v => v.classList.remove('active')); gid(id).classList.add('active'); }
function setActiveNav(id) { document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active')); const el = gid(id); if (el) el.classList.add('active'); }

// ── Chat ──

// Event delegation for clarify option clicks
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.clarify-opt');
  if (!btn) return;
  const action = btn.dataset.action;
  const value = btn.dataset.value;
  if (action === 'refine') {
    gid('queryInput').value = value;
    doQuery();
  } else if (action === 'command') {
    gid('queryInput').value = value;
    doQuery();
  }
});

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

  // Process stages with improved transparency
  if (d.process && d.process.length) {
    html += `<details class="process-details"><summary style="font-size:.75rem;cursor:pointer;color:var(--c-text-secondary)">
      🔍 查询过程 (${d.elapsed_ms||'?'}ms 总耗时)</summary><div class="stage-list">`;
    d.process.forEach(s => {
      const icon = s.status === 'done' ? '✅' : s.status === 'error' ? '❌' : '⏳';
      const cls = s.status === 'done' ? 'stage-ok' : s.status === 'error' ? 'stage-err' : '';
      html += `<div class="stage-item ${cls}"><span class="stage-icon">${icon}</span><span class="stage-name">${s.name}</span><span class="stage-detail">${esc(s.detail||'')}</span><span class="stage-time">${s.elapsed_ms}ms</span></div>`;
    });
    html += '</div></details>';
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

  html += `<div class="msg-meta">${timeNow()} | 🔒 ${esc(d.data_scope||'')}</div></div>`;
  return html;
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

  // Explanation
  if (d.explanation) h += `<div style="font-size:.78rem;color:var(--c-text-secondary);margin-top:6px">${esc(d.explanation)}</div>`;

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

// ── ECharts ──
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

// ── Metrics View ──
async function loadMetrics() {
  gid('metricsContent').innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载中...</div>';
  try {
    const d = await api('/api/metrics');
    gid('metricsContent').innerHTML = renderMetricsList(d);
  } catch(e) {
    gid('metricsContent').innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
  }
}

// ── Snapshots View ──
async function loadSnapshots() {
  gid('snapshotsContent').innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载中...</div>';
  try {
    const d = await api('/api/snapshots');
    gid('snapshotsContent').innerHTML = renderSnapshotsList(d);
  } catch(e) {
    gid('snapshotsContent').innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
  }
}

// ── Import ──
async function doImport(input) {
  const file = input.files[0]; if (!file) return;
  gid('importResult').innerHTML = '<div class="loading-spinner"><div class="spinner"></div>导入中...</div>';
  const fd = new FormData(); fd.append('file', file);
  try {
    const h = {}; if (token) h['Authorization'] = `Bearer ${token}`;
    const r = await fetch('/api/import', { method: 'POST', body: fd, headers: h });
    const d = await r.json();
    gid('importResult').innerHTML = renderImportResult(d);
    loadStatus();
  } catch(e) {
    gid('importResult').innerHTML = `<div class="error-box"><div class="err-title">导入失败</div>${esc(e.message)}</div>`;
  }
  input.value = '';
}

// ── Admin ──
async function adminTab(tab, btn) {
  if (btn) { document.querySelectorAll('.admin-tab').forEach(b => b.classList.remove('active')); btn.classList.add('active'); }
  const c = gid('adminContent');
  c.innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载中...</div>';

  try {
    switch (tab) {
      case 'users': {
        const d = await api('/api/admin/users');
        let h = `<button onclick="showAddUser()" class="btn-primary" style="margin-bottom:12px">+ 添加用户</button>`;
        h += '<table class="data-table"><thead><tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>部门</th><th>区域</th><th>状态</th><th>操作</th></tr></thead><tbody>';
        d.users.forEach(u => {
          h += `<tr>
            <td>${u.user_id}</td><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td>
            <td><span class="role-tag ${u.role}">${u.role}</span></td>
            <td>${esc(u.department)}</td><td>${esc(u.region)}</td>
            <td>${u.is_active?'✅':'❌'}</td>
            <td><button class="btn-sm btn-danger" onclick="toggleUser(${u.user_id})">${u.is_active?'禁用':'启用'}</button></td>
          </tr>`;
        });
        h += '</tbody></table>';
        c.innerHTML = h; break;
      }
      case 'logs': {
        const d = await api('/api/admin/logs?limit=50');
        let h = '<table class="data-table"><thead><tr><th>时间</th><th>用户</th><th>角色</th><th>查询</th><th>状态</th><th>耗时</th></tr></thead><tbody>';
        (d.logs||[]).forEach(l => {
          h += `<tr><td style="font-size:.75rem">${(l.created_at||'').slice(0,19)}</td><td>${esc(l.username)}</td><td>${esc(l.role)}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(l.original_query)}">${esc(l.original_query)}</td><td>${l.status}</td><td>${l.exec_time_ms||0}ms</td></tr>`;
        });
        h += '</tbody></table>';
        c.innerHTML = h; break;
      }
      case 'stats': {
        const d = await api('/api/admin/stats');
        c.innerHTML = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px">
          <div class="stat-card"><div class="stat-num">${d.users}</div><div>用户</div></div>
          <div class="stat-card"><div class="stat-num">${d.snapshots}</div><div>快照</div></div>
          <div class="stat-card"><div class="stat-num">${d.metrics_available}</div><div>可用指标</div></div>
          <div class="stat-card"><div class="stat-num">${d.total_queries}</div><div>总查询</div></div>
          <div class="stat-card"><div class="stat-num">${d.recent_queries}</div><div>近7天查询</div></div>
          <div class="stat-card"><div class="stat-num">${d.active_users}</div><div>活跃用户</div></div>
        </div>
        <style>.stat-card{background:var(--c-surface);padding:20px;border-radius:8px;box-shadow:var(--shadow);text-align:center}.stat-num{font-size:2rem;font-weight:800;color:var(--c-primary)}</style>`; break;
      }
      case 'db': {
        const d = await api('/api/admin/db-tables');
        let h = '';
        d.tables.forEach(t => {
          h += `<details style="margin-bottom:8px"><summary><strong>${esc(t.table_name)}</strong> (${t.row_count} 行)</summary>`;
          h += '<table class="data-table"><thead><tr><th>字段</th><th>类型</th></tr></thead><tbody>';
          (t.columns||[]).forEach(c => h += `<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td></tr>`);
          h += '</tbody></table></details>';
        });
        c.innerHTML = h; break;
      }
    }
  } catch(e) {
    c.innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
  }
}

async function toggleUser(uid) {
  if (!confirm('确认操作?')) return;
  await api(`/api/admin/users/${uid}/toggle`, { method: 'PUT' });
  adminTab('users');
}

function showAddUser() {
  gid('adminContent').innerHTML = `
    <h3>添加用户</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:500px;margin-top:12px">
      <div class="input-group"><label>用户名</label><input id="nu"></div>
      <div class="input-group"><label>密码</label><input type="password" id="np" value="123456"></div>
      <div class="input-group"><label>显示名</label><input id="nd"></div>
      <div class="input-group"><label>角色</label><select id="nr"><option value="employee">employee</option><option value="leader">leader</option><option value="admin">admin</option></select></div>
      <div class="input-group"><label>部门</label><input id="ndep"></div>
      <div class="input-group"><label>区域</label><input id="nreg"></div>
    </div>
    <div style="margin-top:16px"><button onclick="addUser()" class="btn-primary">创建</button> <button onclick="adminTab('users')" class="btn-secondary">取消</button></div>`;
}

async function addUser() {
  const data = { username: gid('nu').value, password: gid('np').value, display_name: gid('nd').value, role: gid('nr').value, department: gid('ndep').value, region: gid('nreg').value };
  await api('/api/admin/users', { method: 'POST', body: JSON.stringify(data) });
  adminTab('users');
}

// ── Helpers ──
function gid(id) { return document.getElementById(id); }
function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function htmlToEl(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; }
function timeNow() { const n = new Date(); return n.getHours().toString().padStart(2,'0') + ':' + n.getMinutes().toString().padStart(2,'0') + ':' + n.getSeconds().toString().padStart(2,'0'); }
