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

export async function login(email, password) {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });

  if (!response.ok) throw await buildApiError(response, 'Login failed');
  return parseAccessToken(response);
}

export async function register(email, password) {
  const response = await fetch('/auth/register', {
    method: 'POST',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({ email, password })
  });

  if (!response.ok) throw await buildApiError(response, 'Register failed');
  return parseAccessToken(response);
}

export async function logout() {
  try {
    const response = await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'include'
    });

    if (!response.ok) throw await buildApiError(response, 'Logout failed');
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
      throw await buildApiError(response, 'Refresh failed');
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
