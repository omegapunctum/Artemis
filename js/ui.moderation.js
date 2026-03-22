import { buildApiError, fetchWithAuth, getCurrentUser } from './auth.js';
import { showError, clearError, showLoading, hideLoading } from './ux.js';
import { createTextElement, toSafeText } from './safe-dom.js';

let moderationInitialized = false;

const moderationState = {
  queue: [],
  isAdmin: false,
  isLoading: false
};

export async function loadModerationQueue() {
  const panel = document.getElementById('moderation-panel');
  const list = document.getElementById('moderation-list');

  if (!panel || !list) return [];

  moderationState.isLoading = true;
  showLoading();

  try {
    const response = await fetchWithAuth('/moderation/queue', { method: 'GET' });

    if (response.status === 403) {
      moderationState.isAdmin = false;
      moderationState.queue = [];
      hideModerationPanel(panel, list);
      return [];
    }

    const data = await parseModerationResponse(response, 'Не удалось загрузить очередь модерации.');
    moderationState.isAdmin = true;
    moderationState.queue = Array.isArray(data) ? data : [];
    clearError();
    renderModerationList();
    return cloneQueue();
  } catch (error) {
    if (error?.status >= 500 || error?.responseStatus >= 500) {
      console.error('Ошибка загрузки очереди модерации:', error);
    }
    showError(error?.message || 'Не удалось загрузить очередь модерации.');
    throw error;
  } finally {
    moderationState.isLoading = false;
    hideLoading();
  }
}

export async function approveDraft(id) {
  showLoading();
  try {
    const response = await fetchWithAuth(`/moderation/${id}/approve`, { method: 'POST' });

    if (response.status === 403) {
      moderationState.isAdmin = false;
      moderationState.queue = [];
      renderModerationList();
      return cloneQueue();
    }

    await parseModerationResponse(response, 'Не удалось одобрить черновик.');
    moderationState.queue = moderationState.queue.filter((draft) => String(draft?.id) !== String(id));
    clearError();
    renderModerationList();
    return cloneQueue();
  } catch (error) {
    showError(error?.message || 'Не удалось одобрить черновик.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function rejectDraft(id) {
  showLoading();
  try {
    const response = await fetchWithAuth(`/moderation/${id}/reject`, { method: 'POST' });

    if (response.status === 403) {
      moderationState.isAdmin = false;
      moderationState.queue = [];
      renderModerationList();
      return cloneQueue();
    }

    await parseModerationResponse(response, 'Не удалось отклонить черновик.');
    moderationState.queue = moderationState.queue.filter((draft) => String(draft?.id) !== String(id));
    clearError();
    renderModerationList();
    return cloneQueue();
  } catch (error) {
    showError(error?.message || 'Не удалось отклонить черновик.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function initModerationUI() {
  if (moderationInitialized) return;
  moderationInitialized = true;

  renderModerationList();

  document.addEventListener('click', handleModerationClick);
  window.addEventListener('artemis:auth-changed', syncModerationPanel, { passive: true });

  await syncModerationPanel();
}

async function syncModerationPanel() {
  const panel = document.getElementById('moderation-panel');
  const list = document.getElementById('moderation-list');

  if (!panel || !list) return;

  if (!getCurrentUser()) {
    moderationState.isAdmin = false;
    moderationState.queue = [];
    hideModerationPanel(panel, list);
    return;
  }

  try {
    await loadModerationQueue();
  } catch (error) {
    if (error?.status === 403 || error?.responseStatus === 403) {
      moderationState.isAdmin = false;
      moderationState.queue = [];
      hideModerationPanel(panel, list);
      return;
    }
    if (error?.status >= 500 || error?.responseStatus >= 500) {
      console.error('Ошибка синхронизации модерации:', error);
    }
  }
}

async function handleModerationClick(event) {
  const button = event.target.closest('[data-moderation-action]');
  if (!button) return;

  const { moderationAction, moderationId } = button.dataset;
  if (!moderationAction || !moderationId) return;

  button.disabled = true;

  try {
    if (moderationAction === 'approve') await approveDraft(moderationId);
    if (moderationAction === 'reject') await rejectDraft(moderationId);
  } catch (error) {
    if (error?.status >= 500 || error?.responseStatus >= 500) {
      console.error(`Ошибка ${moderationAction} черновика:`, error);
    }
  } finally {
    button.disabled = false;
  }
}

function renderModerationList() {
  const panel = document.getElementById('moderation-panel');
  const list = document.getElementById('moderation-list');
  if (!panel || !list) return;

  panel.hidden = !moderationState.isAdmin;
  list.replaceChildren();

  if (!moderationState.isAdmin) return;

  if (!moderationState.queue.length) {
    const empty = document.createElement('div');
    empty.className = 'moderation-empty';
    empty.textContent = moderationState.isLoading ? 'Загрузка…' : 'Черновиков на модерации нет';
    list.appendChild(empty);
    return;
  }

  moderationState.queue.forEach((draft) => {
    const item = document.createElement('div');
    item.className = 'moderation-item';

    const title = createTextElement('strong', draft?.title || draft?.title_short || draft?.name_ru, { fallback: 'Без названия' });
    item.appendChild(title);

    item.appendChild(createTextElement('p', shortenText(draft?.description || '')));

    const actions = document.createElement('div');
    actions.className = 'moderation-actions';

    const approveButton = document.createElement('button');
    approveButton.type = 'button';
    approveButton.dataset.moderationAction = 'approve';
    approveButton.dataset.moderationId = String(draft?.id || '');
    approveButton.textContent = 'Approve';

    const rejectButton = document.createElement('button');
    rejectButton.type = 'button';
    rejectButton.dataset.moderationAction = 'reject';
    rejectButton.dataset.moderationId = String(draft?.id || '');
    rejectButton.textContent = 'Reject';

    actions.append(approveButton, rejectButton);
    item.appendChild(actions);
    list.appendChild(item);
  });
}

function hideModerationPanel(panel, list) {
  panel.hidden = true;
  list.replaceChildren();
}

function cloneQueue() {
  return moderationState.queue.map((draft) => ({ ...draft }));
}

async function parseModerationResponse(response, fallbackMessage) {
  let data = null;

  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }

  if (response.ok) return data;
  if (response.status >= 500) console.error(fallbackMessage, data || response.statusText);
  response.json = async () => data;
  throw await buildApiError(response, fallbackMessage);
}


function shortenText(value) {
  const normalized = toSafeText(value).trim();
  if (!normalized) return 'Без описания';
  return normalized.length > 140 ? `${normalized.slice(0, 137)}...` : normalized;
}

