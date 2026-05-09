/**
 * NSE AI Platform — Client-side Auth Manager
 * Handles JWT storage, user parsing, and auth guards.
 */

const AUTH_TOKEN_KEY = 'nse_ai_token';
const AUTH_USER_KEY  = 'nse_ai_user';
const AUTH_API_BASE  = 'http://localhost:8000';

const auth = {

  // ── Token storage ────────────────────────────────────────────────────────
  getToken() { return localStorage.getItem(AUTH_TOKEN_KEY); },
  setToken(token) { localStorage.setItem(AUTH_TOKEN_KEY, token); },
  clearToken() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  },

  // ── User parsing ─────────────────────────────────────────────────────────
  getUser() {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    if (raw) { try { return JSON.parse(raw); } catch (_) {} }
    return null;
  },
  setUser(user) { localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user)); },

  // ── State ─────────────────────────────────────────────────────────────────
  isLoggedIn() {
    const token = this.getToken();
    if (!token) return false;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp * 1000 > Date.now();
    } catch (_) { return false; }
  },

  // ── Guards ────────────────────────────────────────────────────────────────
  requireAuth() {
    if (!this.isLoggedIn()) {
      window.location.href = 'login.html';
      return false;
    }
    return true;
  },
  requireGuest() {
    if (this.isLoggedIn()) {
      window.location.href = 'index.html';
      return false;
    }
    return true;
  },

  // ── Actions ───────────────────────────────────────────────────────────────
  async logout() {
    this.clearToken();
    window.location.href = 'login.html';
  },

  // ── API calls ─────────────────────────────────────────────────────────────
  async _post(path, body) {
    const res = await fetch(AUTH_API_BASE + path, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    return data;
  },

  async register(name, email, password) {
    const data = await this._post('/api/auth/register', { name, email, password });
    this.setToken(data.access_token);
    this.setUser(data.user);
    return data.user;
  },

  async login(email, password) {
    const data = await this._post('/api/auth/login', { email, password });
    this.setToken(data.access_token);
    this.setUser(data.user);
    return data.user;
  },

  async googleAuth(credential) {
    const data = await this._post('/api/auth/google', { credential });
    this.setToken(data.access_token);
    this.setUser(data.user);
    return data.user;
  },

  async refreshMe() {
    const token = this.getToken();
    if (!token) return null;
    try {
      const res  = await fetch(AUTH_API_BASE + '/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) { this.clearToken(); return null; }
      const user = await res.json();
      this.setUser(user);
      return user;
    } catch (_) { return null; }
  },

  // ── Navbar injection ──────────────────────────────────────────────────────
  injectNavUser() {
    const user = this.getUser();
    const meta = document.querySelector('.nav-meta');
    if (!meta || !user) return;

    const initials = user.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

    const userEl = document.createElement('div');
    userEl.className = 'nav-user';
    userEl.innerHTML = `
      ${user.avatar_url
        ? `<img src="${user.avatar_url}" class="nav-avatar" alt="${user.name}" />`
        : `<div class="nav-avatar-initials">${initials}</div>`}
      <span class="nav-user-name">${user.name.split(' ')[0]}</span>
      <button class="nav-logout-btn" onclick="auth.logout()" title="Sign out">↩</button>
    `;
    meta.prepend(userEl);
  },
};

