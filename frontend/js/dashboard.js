/* 智慧问数系统 v2.0 */

async function showDashboard() {
  switchView('dashboardView'); setActiveNav('navDashboard');
  loadDashboard();
}
async function loadDashboard() {
  const c = gid('dashboardContent');
  try {
    const d = await api('/api/dashboard');
    gid('dashboardPeriod').textContent = d.updated_at ? `数据期间: ${d.updated_at}` : '';

    let h = '';

    // Stat cards
    if (d.cards && d.cards.length) {
      h += '<div class="dash-cards">';
      d.cards.forEach(card => {
        const cls = card.alert_level === '紧急' ? 'danger' : card.alert_level === '重要' ? 'warning' : '';
        const val = card.value != null ? (typeof card.value === 'number' ? card.value.toLocaleString() : card.value) : '—';
        h += `<div class="dash-card ${cls}" onclick="quickQuery('${esc(card.metric_name)}')" title="点击查询详情">
          <div class="dash-card-icon">${card.icon}</div>
          <div class="dash-card-value">${val}<span class="dash-card-unit">${esc(card.unit||'')}</span></div>
          <div class="dash-card-label">${esc(card.label)}</div>
        </div>`;
      });
      h += '</div>';
    }

    // Alert cards
    if (d.alerts && d.alerts.length) {
      h += '<div class="dash-alerts">';
      d.alerts.forEach(a => {
        const alarmIcons = {'紧急':'🔴','重要':'🔶'};
        h += `<div class="dash-alert-card" onclick="quickQuery('${esc(a.metric)}')">
          <span>${alarmIcons[a.alert_level]||'⚠️'} ${esc(a.metric)}</span>
          <strong>${(a.value||0).toLocaleString()} ${esc(a.unit||'')}</strong>
        </div>`;
      });
      h += '</div>';
    }

    // Distribution chart placeholder
    if (d.distribution) {
      h += '<div style="margin-top:20px"><h3 style="margin-bottom:8px;font-size:.95rem">🗺️ 各地市中标分布</h3>';
      h += '<div class="chart-container" id="dashChart"></div></div>';
    }

    c.innerHTML = h;

    // Render chart
    if (d.distribution) {
      setTimeout(() => {
        const el = document.getElementById('dashChart');
        if (!el) return;
        const chart = echarts.init(el);
        const labels = d.distribution.labels.slice(0, 10).reverse();
        const values = d.distribution.values.slice(0, 10).reverse();
        chart.setOption({
          tooltip: { trigger: 'axis' },
          grid: { left: 100, right: 20, top: 10, bottom: 20 },
          xAxis: { type: 'value' },
          yAxis: { type: 'category', data: labels, axisLabel: { fontSize: 11 } },
          series: [{
            type: 'bar', data: values,
            itemStyle: { color: '#4f46e5', borderRadius: [0,4,4,0] },
            barMaxWidth: 24,
          }]
        });
      }, 300);
    }
  } catch(e) {
    c.innerHTML = `<div class="error-box">加载仪表盘失败: ${esc(e.message)}</div>`;
  }
}
function showMetrics() { switchView('metricsView'); setActiveNav('navMetrics'); loadMetrics(); }
function showSnapshots() { switchView('snapshotsView'); setActiveNav('navSnapshots'); loadSnapshots(); }
function showImport() { switchView('importView'); setActiveNav('navImport'); }
function showAdmin() { switchView('adminView'); setActiveNav('navAdmin'); adminTab('users'); }
function switchView(id) { document.querySelectorAll('.view').forEach(v => v.classList.remove('active')); gid(id).classList.add('active'); }
function setActiveNav(id) { document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active')); const el = gid(id); if (el) el.classList.add('active'); }
async function loadMetrics() {
  gid('metricsContent').innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载中...</div>';
  try {
    const d = await api('/api/metrics');
    gid('metricsContent').innerHTML = renderMetricsList(d);
  } catch(e) {
    gid('metricsContent').innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
  }
}
async function loadSnapshots() {
  gid('snapshotsContent').innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载中...</div>';
  try {
    const d = await api('/api/snapshots');
    gid('snapshotsContent').innerHTML = renderSnapshotsList(d);
  } catch(e) {
    gid('snapshotsContent').innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
  }
}
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
