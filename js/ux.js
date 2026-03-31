let loadingCounter = 0;
let messageTimerId = null;

const ERROR_MESSAGES = {
  network: 'Network error. Please check your connection and try again.',
  unauthorized: 'Session expired. Please sign in again.',
  forbidden: 'You do not have access to this action.',
  validation: 'Please check the highlighted fields and try again.',
  server: 'Server error. Please try again later.',
  offline: 'You are offline. This action requires an internet connection.',
  unknown: 'Something went wrong. Please try again.'
};

export function debounce(fn, delay) {
  let timerId = null;
  return function debounced(...args) {
    window.clearTimeout(timerId);
    timerId = window.setTimeout(() => fn.apply(this, args), delay);
  };
}

export function normalizeAppError(error, fallbackMessage = ERROR_MESSAGES.unknown) {
  if (!error) return { kind: 'unknown', message: fallbackMessage, status: 0 };

  const status = Number(error.status || error.responseStatus || error.code || 0);
  if (status === 401) return { kind: 'unauthorized', message: ERROR_MESSAGES.unauthorized, status };
  if (status === 403) return { kind: 'forbidden', message: ERROR_MESSAGES.forbidden, status };
  if (status === 400 || status === 409 || status === 422) return { kind: 'validation', message: ERROR_MESSAGES.validation, status };
  if (status >= 500) return { kind: 'server', message: ERROR_MESSAGES.server, status };

  const rawMessage = String(error.message || '').toLowerCase();
  if (error.name === 'TypeError' || rawMessage.includes('network') || rawMessage.includes('failed to fetch')) {
    return { kind: 'network', message: ERROR_MESSAGES.network, status };
  }

  return { kind: 'unknown', message: fallbackMessage || ERROR_MESSAGES.unknown, status };
}

export function createInlineStateBlock({
  variant = 'info',
  title = '',
  message = '',
  actionLabel = '',
  onAction = null,
  ariaLive = 'polite'
} = {}) {
  const block = document.createElement('div');
  block.className = `app-state-block app-state-${variant}`;
  block.setAttribute('role', variant === 'error' ? 'alert' : 'status');
  block.setAttribute('aria-live', ariaLive);

  if (title) {
    const heading = document.createElement('div');
    heading.className = 'app-state-title';
    heading.textContent = title;
    block.appendChild(heading);
  }

  if (message) {
    const body = document.createElement('div');
    body.className = 'app-state-message';
    body.textContent = message;
    block.appendChild(body);
  }

  if (actionLabel && typeof onAction === 'function') {
    const actions = document.createElement('div');
    actions.className = 'app-state-actions';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'app-state-action-btn';
    button.textContent = actionLabel;
    button.setAttribute('aria-label', actionLabel);
    button.addEventListener('click', onAction);
    actions.appendChild(button);
    block.appendChild(actions);
  }

  return block;
}

export function renderInlineState(host, config = {}) {
  if (!host) return;
  host.replaceChildren(createInlineStateBlock(config));
}

export function clearInlineState(host) {
  if (!host) return;
  host.replaceChildren();
}

export function showSystemMessage(message, { variant = 'success', timeout = 2600 } = {}) {
  const host = document.getElementById('app-status-host');
  if (!host || !message) return;

  const item = document.createElement('div');
  item.className = `app-system-message app-system-${variant}`;
  item.setAttribute('role', 'status');
  item.setAttribute('aria-live', 'polite');
  item.textContent = message;

  host.appendChild(item);
  window.clearTimeout(messageTimerId);
  messageTimerId = window.setTimeout(() => {
    item.remove();
  }, timeout);
}

export function setOfflineState(offline) {
  const badge = document.getElementById('offline-status');
  if (!badge) return;
  badge.hidden = !offline;
}

export function isOffline() {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

export function ensureOnlineAction() {
  if (!isOffline()) return true;
  showSystemMessage('You are offline', { variant: 'warning', timeout: 3200 });
  return false;
}

export function showError(message) {
  const banner = document.getElementById('error-banner');
  if (!banner) return;
  banner.textContent = String(message || ERROR_MESSAGES.unknown);
  banner.hidden = false;
}

export function clearError() {
  const banner = document.getElementById('error-banner');
  if (!banner) return;
  banner.hidden = true;
  banner.textContent = '';
}

export function showLoading() {
  const indicator = document.getElementById('loading-indicator');
  if (!indicator) return;
  loadingCounter += 1;
  indicator.hidden = false;
}

export function hideLoading() {
  const indicator = document.getElementById('loading-indicator');
  if (!indicator) return;
  loadingCounter = Math.max(0, loadingCounter - 1);
  indicator.hidden = loadingCounter > 0;
}
