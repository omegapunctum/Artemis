let accessToken = null;
let refreshPromise = null;

function authRequired() {
  window.dispatchEvent(new CustomEvent('artemis:auth-required'));
}

function withAuthHeaders(headers = {}) {
  const result = new Headers(headers);
  if (accessToken) {
    result.set('Authorization', `Bearer ${accessToken}`);
  }
  return result;
}

async function parseAccessToken(response) {
  const data = await response.json();
  const token = data?.access_token ?? data?.accessToken ?? null;
  if (!token) throw new Error('Access token missing');
  accessToken = token;
  return data;
}

export function setAccessToken(token) {
  accessToken = token || null;
}

export function getAccessToken() {
  return accessToken;
}

export function clearAuth() {
  accessToken = null;
}

export function getCurrentUser() {
  return accessToken ? { accessToken } : null;
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

async function refreshToken() {
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

export async function fetchWithAuth(url, options = {}, retried = false) {
  const response = await fetch(url, {
    ...options,
    headers: withAuthHeaders(options.headers),
    credentials: 'include'
  });

  if (response.status !== 401 || retried) {
    return response;
  }

  try {
    await refreshToken();
  } catch (error) {
    clearAuth();
    authRequired();
    throw error;
  }

  return fetchWithAuth(url, options, true);
}

export const apiFetch = fetchWithAuth;
