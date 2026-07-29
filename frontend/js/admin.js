/* 智慧问数系统 v2.0 */

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
      case 'suggestions': {
        c.innerHTML = '<div class="loading-spinner"><div class="spinner"></div>加载建议...</div>';
        try {
          const d = await api('/api/admin/suggestions?limit=50');
          let h = `<h3 style="margin-bottom:8px">💡 反馈改进建议</h3>
            <div style="display:flex;gap:16px;margin-bottom:16px;font-size:.85rem;color:var(--c-text-secondary)">
              <span>总计: ${d.stats.total||0}</span>
              <span style="color:var(--c-warning)">待处理: ${d.stats.pending||0}</span>
              <span style="color:var(--c-success)">已应用: ${d.stats.applied||0}</span>
            </div>`;

          if (d.items && d.items.length > 0) {
            d.items.forEach(item => {
              const typeLabels = { sql_correction: '🔧 SQL修正', term_mapping: '📝 术语映射', general_improvement: '💬 改进建议' };
              h += `<div style="background:var(--c-surface);border-radius:8px;padding:12px;margin-bottom:8px;box-shadow:var(--shadow)">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                  <span><strong>${typeLabels[item.suggestion_type]||item.suggestion_type}</strong></span>
                  <span style="font-size:.72rem;color:var(--c-text-secondary)">${(item.created_at||'').slice(0,16)}</span>
                </div>
                <div style="font-size:.82rem;color:var(--c-text-secondary);margin-bottom:4px">${esc(item.user_comment)}</div>
                <div style="font-size:.78rem;background:#f1f5f9;padding:6px 8px;border-radius:4px;margin-bottom:8px">
                  <span style="color:var(--c-text-secondary)">原始查询: </span>${esc(item.original_query||'?')}
                  ${item.matched_metric ? `<span style="margin-left:12px;color:var(--c-text-secondary)">匹配: </span>${esc(item.matched_metric)}` : ''}
                </div>
                <div>
                  <button class="btn-sm" style="background:var(--c-success);color:#fff" onclick="applySuggestion(${item.suggestion_id})">✅ 应用</button>
                  <button class="btn-sm btn-danger" style="margin-left:4px" onclick="dismissSuggestion(${item.suggestion_id})">❌ 忽略</button>
                </div>
              </div>`;
            });
          } else {
            h += '<div style="padding:40px;text-align:center;color:var(--c-text-secondary)">暂无改进建议。当用户对查询结果不满意并提供反馈时，系统会自动分析生成建议。</div>';
          }
          c.innerHTML = h;
        } catch(e) {
          c.innerHTML = `<div class="error-box"><div class="err-title">加载失败</div>${esc(e.message)}</div>`;
        }
        break;
      }
      case 'onboarding': {
        c.innerHTML = '<div class="loading-spinner"><div class="spinner"></div>扫描数据表...</div>';
        try {
          // 扫描可接入的表
          const scan = await api('/api/admin/onboarding/scan');
          let h = `<h3 style="margin-bottom:8px">🔌 数据接入流水线</h3>
            <p style="color:var(--c-text-secondary);font-size:.85rem;margin-bottom:16px">
            自动发现数据库中的业务表, 评估质量, 生成指标, 提交审核</p>`;

          if (scan.tables && scan.tables.length > 0) {
            h += `<table class="data-table"><thead><tr>
              <th>表名</th><th>行数</th><th>列数</th><th>字段数</th><th>操作</th>
            </tr></thead><tbody>`;
            scan.tables.forEach(t => {
              h += `<tr>
                <td><strong>${esc(t.table_name)}</strong></td>
                <td>${(t.row_count||0).toLocaleString()}</td>
                <td>${t.column_count||0}</td>
                <td>${t.fields||0}</td>
                <td>
                  <button class="btn-sm btn-primary" onclick="onboardAnalyze('${esc(t.table_name)}')">分析</button>
                  <button class="btn-sm" style="background:var(--c-success);color:#fff;margin-left:4px" onclick="onboardSubmit('${esc(t.table_name)}')">一键接入</button>
                </td>
              </tr>`;
            });
            h += '</tbody></table>';
          } else {
            h += '<div style="padding:20px;text-align:center;color:var(--c-text-secondary)">未发现可接入的业务表</div>';
          }

          // 审核队列
          try {
            const q = await api('/api/admin/onboarding/queue');
            if (q.items && q.items.length > 0) {
              h += `<h3 style="margin:24px 0 8px">📋 审核队列 (${q.items.length})</h3>`;
              h += '<table class="data-table"><thead><tr><th>表名</th><th>质量分</th><th>状态</th><th>操作</th></tr></thead><tbody>';
              q.items.forEach(item => {
                h += `<tr>
                  <td>${esc(item.table_name)}</td>
                  <td><span style="font-weight:700;color:${item.quality_score>=75?'var(--c-success)':item.quality_score>=60?'var(--c-warning)':'var(--c-danger)'}">${item.quality_score}分</span></td>
                  <td>${item.status==='pending'?'⏳待审核':item.status}</td>
                  <td>
                    <button class="btn-sm" style="background:var(--c-success);color:#fff" onclick="onboardApprove(${item.queue_id})">通过</button>
                    <button class="btn-sm btn-danger" style="margin-left:4px" onclick="onboardReject(${item.queue_id})">拒绝</button>
                  </td>
                </tr>`;
              });
              h += '</tbody></table>';
            }
          } catch(e) {}

          c.innerHTML = h;
        } catch(e) {
          c.innerHTML = `<div class="error-box"><div class="err-title">扫描失败</div>${esc(e.message)}</div>`;
        }
        break;
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
async function onboardAnalyze(tableName) {
  const c = gid('adminContent');
  c.innerHTML = '<div class="loading-spinner"><div class="spinner"></div>分析中...</div>';
  try {
    const d = await api(`/api/admin/onboarding/analyze/${encodeURIComponent(tableName)}`);
    let h = `<h3>📊 ${esc(tableName)} 分析报告</h3>`;

    // 质量评分
    const q = d.quality;
    const gradeColor = q.score >= 75 ? 'var(--c-success)' : q.score >= 60 ? 'var(--c-warning)' : 'var(--c-danger)';
    h += `<div style="display:flex;gap:16px;margin:12px 0">
      <div class="stat-card"><div class="stat-num" style="color:${gradeColor}">${q.score}</div><div>质量评分 (${q.grade})</div></div>
      <div class="stat-card"><div class="stat-num">${q.total_issues}</div><div>问题数</div></div>
      <div class="stat-card"><div class="stat-num">${d.dataset_type.type}</div><div>数据集类型</div></div>
    </div>`;

    // 字段详情
    if (d.metadata && d.metadata.fields) {
      h += '<h4 style="margin-top:16px">字段列表</h4>';
      h += '<table class="data-table"><thead><tr><th>字段</th><th>类型</th><th>示例值</th></tr></thead><tbody>';
      d.metadata.fields.forEach(f => {
        h += `<tr><td>${esc(f.name)}</td><td>${esc(f.python_type)}</td>
          <td style="font-size:.72rem;color:var(--c-text-secondary)">${esc((f.sample_values||[]).join(', '))}</td></tr>`;
      });
      h += '</tbody></table>';
    }

    // 问题列表
    if (q.issues && q.issues.length > 0) {
      h += '<h4 style="margin-top:16px;color:var(--c-warning)">⚠️ 质量问题</h4>';
      q.issues.forEach(fi => {
        h += `<div style="margin:4px 0;font-size:.82rem"><strong>${esc(fi.field)}:</strong> `;
        fi.issues.forEach(iss => {
          h += `<span style="color:var(--c-text-secondary)">${esc(iss.suggestion)}</span> `;
        });
        h += '</div>';
      });
    }

    h += `<div style="margin-top:16px">
      <button class="btn-primary" onclick="onboardSubmit('${esc(tableName)}')">一键接入</button>
      <button class="btn-secondary" style="margin-left:8px" onclick="adminTab('onboarding')">返回</button>
    </div>`;
    c.innerHTML = h;
  } catch(e) {
    c.innerHTML = `<div class="error-box"><div class="err-title">分析失败</div>${esc(e.message)}</div>`;
  }
}
async function onboardSubmit(tableName) {
  const c = gid('adminContent');
  c.innerHTML = '<div class="loading-spinner"><div class="spinner"></div>接入中...</div>';
  try {
    const d = await api(`/api/admin/onboarding/submit/${encodeURIComponent(tableName)}?auto_approve=true`, { method: 'POST' });
    let h = `<h3>✅ ${esc(tableName)} 接入完成</h3>`;
    h += `<div style="margin:8px 0">质量评分: <strong>${d.quality.score}分 (${d.quality.grade})</strong></div>`;
    h += `<div>数据集类型: <strong>${d.dataset_type.type}</strong> (置信度: ${(d.dataset_type.confidence*100).toFixed(0)}%)</div>`;
    if (d.registration) {
      h += `<div style="margin-top:8px;color:var(--c-success)">✅ 已创建 ${d.registration.metrics_created} 个指标</div>`;
    }
    h += '<div style="margin-top:16px"><button class="btn-primary" onclick="adminTab(\'onboarding\')">返回</button></div>';
    c.innerHTML = h;
  } catch(e) {
    c.innerHTML = `<div class="error-box"><div class="err-title">接入失败</div>${esc(e.message)}</div>`;
  }
}
async function onboardApprove(queueId) {
  await api(`/api/admin/onboarding/approve/${queueId}`, { method: 'POST' });
  adminTab('onboarding');
}
async function onboardReject(queueId) {
  const reason = prompt('拒绝原因 (可选):');
  await api(`/api/admin/onboarding/reject/${queueId}?reason=${encodeURIComponent(reason||'')}`, { method: 'POST' });
  adminTab('onboarding');
}
async function applySuggestion(sid) {
  await api(`/api/admin/suggestions/${sid}/apply`, { method: 'POST' });
  adminTab('suggestions');
}
async function dismissSuggestion(sid) {
  await api(`/api/admin/suggestions/${sid}/dismiss`, { method: 'POST' });
  adminTab('suggestions');
}
