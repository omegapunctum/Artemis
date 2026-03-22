let accessToken = null;
let refreshPromise = null;
let initPromise = null;

function notifyAuthChanged() {
  window.dispatchEvent(new CustomEvent('artemis:auth-changed', { detail: getCurrentUser() }));
}

function authRequired() {
  window.dispatchEvent(new CustomEvent('artemis:auth-required'));
}

function parseTokenClaims(token) {
  try {
    const [, payload] = String(token || '').split('.');
    if (!payload) return {};
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
    return JSON.parse(atob(padded));
  } catch (_error) {
    return {};
  }
}

function normalizeRoles(claims) {
  if (Array.isArray(claims?.roles)) return claims.roles.map((role) => String(role));
  if (typeof claims?.role === 'string' && claims.role) return [claims.role];
  return [];
}

function withAuthHeaders(headers = {}) {
  const result = new Headers(headers);
  if (accessToken) {
    result.set('Authorization', `Bearer ${accessToken}`);
  }
  return result;
}

function buildAuthRequest(input, options = {}) {
  const request = input instanceof Request ? input : new Request(input, options);
  const headers = withAuthHeaders(request.headers);

  return new Request(request, {
    headers,
    credentials: 'include'
  });
}

async function parseAccessToken(response) {
  const data = await response.json();
  const token = data?.access_token ?? data?.accessToken ?? null;
  if (!token) throw new Error('Access token missing');
  accessToken = token;
  notifyAuthChanged();
  return data;
}

export function setAccessToken(token) {
  accessToken = token || null;
  notifyAuthChanged();
}

export function getAccessToken() {
  return accessToken;
}

export function clearAuth() {
  accessToken = null;
  refreshPromise = null;
  initPromise = null;
  notifyAuthChanged();
}

export function getCurrentUser() {
  if (!accessToken) return null;

  const claims = parseTokenClaims(accessToken);
  const roles = normalizeRoles(claims);
  const role = typeof claims?.role === 'string' ? claims.role : (roles[0] || null);

  return {
    accessToken,
    ...claims,
    role,
    roles,
    isAdmin: role === 'admin' || roles.includes('admin')
  };
}

export async function login(email, password) {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });

  if (!response.ok) throw new Error('Login failed');
  return parseAccessToken(response);
}

export async function register(email, password) {
  const response = await fetch('/auth/register', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });

  if (!response.ok) throw new Error('Register failed');
  return parseAccessToken(response);
}

export async function logout() {
  try {
    const response = await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'include'
    });

    if (!response.ok) throw new Error('Logout failed');
  } finally {
    clearAuth();
  }
}

export async function refreshToken() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const response = await fetch('/auth/refresh', {
      method: 'POST',
      credentials: 'include'
    });

    if (!response.ok) {
      clearAuth();
      throw new Error('Refresh failed');
    }

    return parseAccessToken(response);
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

export async function initAuth() {
  if (accessToken) return getCurrentUser();
  if (initPromise) return initPromise;

  // Silent refresh при старте: без ошибок в UI и безопасно для повторного вызова.
  initPromise = (async () => {
    try {
      await refreshToken();
      return getCurrentUser();
    } catch (_error) {
      return null;
    } finally {
      initPromise = null;
    }
  })();

  return initPromise;
}

export async function fetchWithAuth(input, options = {}) {
  const originalRequest = input instanceof Request ? input : new Request(input, options);
  const firstAttempt = buildAuthRequest(originalRequest);
  const response = await fetch(firstAttempt);

  if (response.status !== 401) {
    return response;
  }

  try {
    // Все параллельные 401 ждут один и тот же refresh lock.
    await refreshToken();
  } catch (error) {
    authRequired();
    throw error;
  }

  // Ровно один retry после refresh, без бесконечного цикла.
  const retryRequest = buildAuthRequest(originalRequest.clone());
  return fetch(retryRequest);
}

export const apiFetch = fetchWithAuth;
