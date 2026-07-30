import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

// JWT 拦截器 — 自动附加 token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('sq2_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 401 拦截 — 自动跳转登录
client.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('sq2_token');
      localStorage.removeItem('sq2_user');
      window.location.href = '/';
    }
    return Promise.reject(err);
  }
);

export default client;
