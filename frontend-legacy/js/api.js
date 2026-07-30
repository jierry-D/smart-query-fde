/* ═══════════════════════════════════════════
   智慧问数系统 v2.0 — API层 + 基础工具
   ═══════════════════════════════════════════ */

// ── State ──
let token = null;
let user = null;
let msgId = 0;

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
    showApp(); loadStatus(); showDashboard();
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
  const r = user.role;
  let scope = '全部数据';
  if (r === 'leader') scope = (user.department||'全部') + ' (全部区域)';
  else if (r === 'employee') scope = (user.department||'') + ' - ' + (user.region||'');
  gid('dataScope').textContent = '🔒 ' + scope;
  gid('navImport').style.display = (r === 'admin' || r === 'leader') ? '' : 'none';
  gid('navAdmin').style.display = r === 'admin' ? '' : 'none';
}

async function loadStatus() {
  try {
    const d = await api('/api/status');
    gid('statusInfo').innerHTML = `<span>📅 ${d.date}</span><span>📦 ${d.snapshots} 快照</span><span>📋 ${d.metrics_available}/${d.metrics_total} 指标</span>`;
  } catch(e) {}
}

// ── Helpers ──
function gid(id) { return document.getElementById(id); }
function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function htmlToEl(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; }
function timeNow() { const n = new Date(); return n.getHours().toString().padStart(2,'0') + ':' + n.getMinutes().toString().padStart(2,'0') + ':' + n.getSeconds().toString().padStart(2,'0'); }

// ── Init ──
window.onload = () => {
  const s = localStorage.getItem('sq2');
  if (s) { try { const d = JSON.parse(s); token = d.token; user = d.user; } catch(e) {} }
  if (token) { showApp(); loadStatus(); showDashboard(); } else { showLogin(); }
  setInterval(loadStatus, 60000);
};
