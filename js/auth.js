let accessToken = null;
let refreshPromise = null;
let initPromise = null;
let resolvedApiBase = null;

const API_BASE_CANDIDATES = [
  (window.ARTEMIS_API_BASE || '').trim(),
  document.querySelector('meta[name="artemis-api-base"]')?.getAttribute('content')?.trim() || '',
  '/api',
  ''
].filter((value, index, array) => value !== null && value !== undefined && array.indexOf(value) === index);

function notifyAuthChanged() {
  window.dispatchEvent(new CustomEvent('artemis:auth-changed', { detail: getCurrentUser() }));
}

function authRequired() {
  window.dispatchEvent(new CustomEvent('artemis:auth-required'));
}

function normalizePath(path) {
  const cleanedPath = String(path || '').trim();
  if (!cleanedPath) return '/';
  return cleanedPath.startsWith('/') ? cleanedPath : `/${cleanedPath}`;
}

function buildApiUrl(base, path) {
  const normalizedPath = normalizePath(path);
  if (!base) return normalizedPath;
  const normalizedBase = String(base).replace(/\/+$/, '');
  return `${normalizedBase}${normalizedPath}`;
}

async function requestApi(path, options = {}, fallbackMessage = 'API request failed') {
  const method = String(options?.method || 'GET').toUpperCase();
  const candidates = resolvedApiBase !== null ? [resolvedApiBase] : API_BASE_CANDIDATES;
  let lastResponse = null;

  for (const base of candidates) {
    const url = buildApiUrl(base, path);
    const response = await fetch(url, options);
    lastResponse = response;

    if (response.ok) {
      resolvedApiBase = base;
      return response;
    }

    const canTryFallback = (response.status === 404 || response.status === 405) && resolvedApiBase === null;
    if (!canTryFallback) {
      throw await buildApiError(response, fallbackMessage);
    }

    console.warn('ARTEMIS API route fallback', { method, path, tried: url, status: response.status });
  }

  throw await buildApiError(lastResponse, fallbackMessage);
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

export function formatRequestIdMessage(message, requestId) {
  return requestId ? `${message} (Request ID: ${requestId})` : message;
}

export async function buildApiError(response, fallbackMessage) {
  let data = null;
  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }

  const requestId = response.headers.get('X-Request-ID') || data?.request_id || data?.error?.request_id || null;
  const apiError = typeof data?.error === 'string' ? data.error : data?.error?.message;
  const message = formatRequestIdMessage(apiError || data?.message || fallbackMessage, requestId);
  const error = new Error(message);
  error.status = response.status;
  error.responseStatus = response.status;
  error.requestId = requestId;
  error.payload = data;
  console.error('ARTEMIS API error', {
    message: error.message,
    status: response.status,
    requestId,
    url: response.url
  });
  return error;
}

async function parseAccessToken(response, fallbackMessage = 'Access token missing') {
  const data = await response.json();
  const token = data?.access_token ?? data?.accessToken ?? null;
  if (!token) throw new Error(fallbackMessage);
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

export function canModerate(user = getCurrentUser()) {
  if (!user) return false;
  const role = String(user?.role || '').toLowerCase();
  const roles = Array.isArray(user?.roles) ? user.roles.map((value) => String(value).toLowerCase()) : [];
  return Boolean(user?.isAdmin || role === 'admin' || role === 'moderator' || roles.includes('admin') || roles.includes('moderator'));
}

export async function login(email, password) {
  const response = await requestApi('/auth/login', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  }, 'Login failed');

  return parseAccessToken(response);
}

export async function register(email, password) {
  const response = await requestApi('/auth/register', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  }, 'Регистрация не выполнена. Проверьте URL API и доступность /auth/register.');

  return parseAccessToken(response);
}

export async function logout() {
  try {
    const response = await requestApi('/auth/logout', {
      method: 'POST',
      credentials: 'include'
    }, 'Logout failed');
  } finally {
    clearAuth();
  }
}

export async function refreshToken() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const response = await requestApi('/auth/refresh', {
      method: 'POST',
      credentials: 'include'
    }, 'Refresh failed');

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
    await refreshToken();
  } catch (error) {
    authRequired();
    throw error;
  }

  const retryRequest = buildAuthRequest(originalRequest.clone());
  return fetch(retryRequest);
}

export const apiFetch = fetchWithAuth;
