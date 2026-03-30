import { buildApiError, login, register, logout, getCurrentUser, fetchWithAuth } from './auth.js';
import { submitForModeration, validateDraftPayload } from './ugc.js';
import { loadLayers } from './data.js';
import { showError, clearError, showLoading, hideLoading } from './ux.js';
import { normalizeSafeUrl, setSafeLink, setText, toSafeText } from './safe-dom.js';

let ugcInitialized = false;

const draftState = {
  drafts: []
};

const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;
const VALIDATION_ERROR_MESSAGES = {
  required: 'Обязательное поле.',
  invalid_integer: 'Ожидается целое число.',
  invalid_url_scheme: 'Разрешены только http/https URL.',
  too_long: 'Слишком длинное значение.',
  pair_required: 'Укажите и широту, и долготу.',
  invalid_range: 'Координата вне допустимого диапазона.',
  not_allowed: 'Значение не входит в допустимый список.'
};

export async function uploadImage(file, draftId) {
  if (!file) throw new Error('Файл не выбран.');
  if (!draftId) throw new Error('Сначала сохраните черновик, затем загрузите изображение.');

  if (file.size > MAX_IMAGE_SIZE_BYTES) {
    const error = new Error('Размер файла превышает 5 MB.');
    console.error(error.message);
    if (typeof window !== 'undefined' && typeof window.alert === 'function') window.alert(error.message);
    throw error;
  }

  const formData = new FormData();
  formData.append('file', file);
  formData.append('draft_id', String(draftId));

  showLoading();
  try {
    const response = await fetchWithAuth('/uploads/image', {
      method: 'POST',
      body: formData
    });

    const data = await parseDraftResponse(response, 'Не удалось загрузить изображение.');
    clearError();
    return String(data?.url || '').trim();
  } catch (error) {
    showError(error.message || 'Не удалось загрузить изображение.');
    throw error;
  } finally {
    hideLoading();
  }
}

function cloneDrafts() {
  return draftState.drafts.map((draft) => ({ ...draft }));
}

function normalizeDraft(draft) {
  if (!draft || typeof draft !== 'object') return null;

  const coords = Array.isArray(draft.coords)
    ? draft.coords
    : (draft.geometry?.type === 'Point' && Array.isArray(draft.geometry.coordinates) ? draft.geometry.coordinates : null);

  return {
    ...draft,
    coords: Array.isArray(coords) ? coords : null
  };
}

async function parseDraftResponse(response, fallbackMessage) {
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

export async function loadDrafts() {
  showLoading();
  try {
    const response = await fetchWithAuth('/drafts', { method: 'GET' });
    const data = await parseDraftResponse(response, 'Не удалось загрузить черновики.');
    draftState.drafts = Array.isArray(data) ? data.map(normalizeDraft).filter(Boolean) : [];
    clearError();
    return cloneDrafts();
  } catch (error) {
    showError(error.message || 'Не удалось загрузить черновики.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function createDraft(data) {
  const check = validateDraftPayload(data);
  if (!check.valid) {
    const error = new Error('Ошибка валидации.');
    error.type = 'validation';
    error.fields = check.errors;
    throw error;
  }

  showLoading();
  try {
    const response = await fetchWithAuth('/drafts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(check.data)
    });
    const createdDraft = normalizeDraft(await parseDraftResponse(response, 'Не удалось создать черновик.'));
    if (createdDraft) draftState.drafts = [createdDraft, ...draftState.drafts.filter((draft) => draft.id !== createdDraft.id)];
    clearError();
    return createdDraft;
  } catch (error) {
    showError(error.message || 'Не удалось создать черновик.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function updateDraft(id, data) {
  const check = validateDraftPayload(data);
  if (!check.valid) {
    const error = new Error('Ошибка валидации.');
    error.type = 'validation';
    error.fields = check.errors;
    throw error;
  }

  showLoading();
  try {
    const response = await fetchWithAuth(`/drafts/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(check.data)
    });
    const updatedDraft = normalizeDraft(await parseDraftResponse(response, 'Не удалось обновить черновик.'));
    if (updatedDraft) {
      const hasDraft = draftState.drafts.some((draft) => draft.id === updatedDraft.id);
      draftState.drafts = hasDraft
        ? draftState.drafts.map((draft) => (draft.id === updatedDraft.id ? updatedDraft : draft))
        : [updatedDraft, ...draftState.drafts];
    }
    clearError();
    return updatedDraft;
  } catch (error) {
    showError(error.message || 'Не удалось обновить черновик.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function deleteDraft(id) {
  showLoading();
  try {
    const response = await fetchWithAuth(`/drafts/${id}`, { method: 'DELETE' });
    await parseDraftResponse(response, 'Не удалось удалить черновик.');
    draftState.drafts = draftState.drafts.filter((draft) => String(draft.id) !== String(id));
    clearError();
    return cloneDrafts();
  } catch (error) {
    showError(error.message || 'Не удалось удалить черновик.');
    throw error;
  } finally {
    hideLoading();
  }
}

export async function initUGCUI() {
  if (ugcInitialized) return;
  ugcInitialized = true;

  const els = {
    authButtons: document.getElementById('auth-buttons'),
    loginBtn: document.getElementById('login-btn'),
    registerBtn: document.getElementById('register-btn'),
    profilePanel: document.getElementById('profile-panel'),
    draftsList: document.getElementById('drafts-list'),
    openDraftEditorBtn: document.getElementById('open-draft-editor-btn'),
    refreshDraftsBtn: document.getElementById('refresh-drafts-btn'),
    logoutBtn: document.getElementById('logout-btn'),
    loginModal: document.getElementById('login-modal'),
    loginForm: document.getElementById('login-form'),
    draftModal: document.getElementById('draft-modal'),
    draftForm: document.getElementById('draft-form'),
    draftErrors: document.getElementById('draft-errors')
  };

  const state = {
    activeDraftId: null,
    pendingAfterLogin: null,
    layers: await loadLayers().catch(() => []),
    isRefreshingDrafts: false
  };

  hydrateLayerSelect(state.layers);
  bindModalClosers(els);
  bindAuth(els, state);
  bindDraftEditor(els, state);
  syncAuthUI(els);

  if (getCurrentUser()) {
    await refreshDraftsList(els, state);
  }

  window.addEventListener('artemis:auth-required', () => {
    state.pendingAfterLogin = state.pendingAfterLogin || 'restore-session';
    openModal(els.loginModal);
  }, { passive: true });
}

function bindAuth(els, state) {
  els.loginBtn.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'login';
    openModal(els.loginModal);
  });

  els.registerBtn.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'register';
    openModal(els.loginModal);
  });

  els.loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const mode = els.loginForm.dataset.mode || 'login';
    const email = els.loginForm.email.value.trim();
    const password = els.loginForm.password.value;

    setLoading(els.loginForm, true);
    try {
      if (mode === 'register') await register(email, password);
      else await login(email, password);
      closeModal(els.loginModal);
      syncAuthUI(els);
      await refreshDraftsList(els, state);
      showToast('Авторизация успешна.');

      if (state.pendingAfterLogin === 'open-editor') {
        state.pendingAfterLogin = null;
        openDraftEditor(els, state, null);
      } else {
        state.pendingAfterLogin = null;
      }
    } catch (error) {
      console.error('Ошибка авторизации:', error);
      showToast(error.message || 'Ошибка авторизации.');
    } finally {
      setLoading(els.loginForm, false);
    }
  });

  els.logoutBtn.addEventListener('click', async () => {
    await logout();
    syncAuthUI(els);
    els.draftsList.replaceChildren();
    draftState.drafts = [];
    state.activeDraftId = null;
    closeModal(els.draftModal);
    showToast('Вы вышли из аккаунта.');
  });
}

function bindDraftEditor(els, state) {
  els.openDraftEditorBtn.addEventListener('click', () => {
    if (!getCurrentUser()) {
      state.pendingAfterLogin = 'open-editor';
      els.loginForm.dataset.mode = 'login';
      openModal(els.loginModal);
      return;
    }
    openDraftEditor(els, state, null);
  });

  els.refreshDraftsBtn.addEventListener('click', async () => {
    if (!getCurrentUser()) {
      openModal(els.loginModal);
      return;
    }
    await refreshDraftsList(els, state);
  });

  els.draftForm.image_file.addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!state.activeDraftId) {
      const message = 'Сначала сохраните черновик, затем загрузите изображение.';
      console.error(message);
      window.alert?.(message);
      event.target.value = '';
      return;
    }

    try {
      setLoading(els.draftForm, true);
      const imageUrl = await uploadImage(file, state.activeDraftId);
      draftState.drafts = draftState.drafts.map((draft) => (
        String(draft.id) === String(state.activeDraftId)
          ? { ...draft, image_url: imageUrl, source_media_url: imageUrl }
          : draft
      ));
      els.draftForm.source_media_url.value = imageUrl;
      await refreshDraftsList(els, state);
      const refreshedDraft = draftState.drafts.find((draft) => String(draft.id) === String(state.activeDraftId));
      if (refreshedDraft) openDraftEditor(els, state, { ...refreshedDraft, source_media_url: imageUrl });
      showToast('Изображение прикреплено к черновику.');
    } catch (error) {
      console.error('Ошибка загрузки изображения:', error);
      handlePossiblyUnauthorized(error, state, els);
      showToast(error.message || 'Не удалось загрузить изображение.');
    } finally {
      event.target.value = '';
      setLoading(els.draftForm, false);
    }
  });

  els.draftForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const payload = collectDraftPayload(els.draftForm);
    const check = validateDraftPayload(payload);
    if (!check.valid) {
      renderFieldErrors(els.draftForm, els.draftErrors, check.errors);
      return;
    }

    setLoading(els.draftForm, true);
    renderFieldErrors(els.draftForm, els.draftErrors, {});
    try {
      if (state.activeDraftId) {
        await updateDraft(state.activeDraftId, payload);
        showToast('Черновик обновлён.');
      } else {
        await createDraft(payload);
        showToast('Черновик создан.');
      }
      closeModal(els.draftModal);
      await refreshDraftsList(els, state);
    } catch (error) {
      console.error('Ошибка сохранения черновика:', error);
      if (error.type === 'validation') {
        renderFieldErrors(els.draftForm, els.draftErrors, error.fields || {});
      } else if (error.type === 'auth' || String(error.message || '').includes('Требуется повторный вход')) {
        state.pendingAfterLogin = 'open-editor';
        showToast('Нужна авторизация.');
        openModal(els.loginModal);
      } else {
        showToast(error.message || 'Не удалось сохранить черновик.');
      }
    } finally {
      setLoading(els.draftForm, false);
    }
  });
}

// Обновляет список черновиков без перезагрузки страницы.
async function refreshDraftsList(els, state) {
  if (state.isRefreshingDrafts) return;
  state.isRefreshingDrafts = true;
  try {
    const drafts = await loadDrafts();
    els.draftsList.replaceChildren();

    drafts.forEach((draft) => {
      const item = document.createElement('li');
      item.className = 'draft-item';

      const title = document.createElement('strong');
      title.textContent = String(draft?.name_ru || 'Без названия');
      item.appendChild(title);

      const status = document.createElement('span');
      status.className = 'status-label';
      status.textContent = humanStatus(draft?.status);
      item.appendChild(status);

      const safeImageUrl = normalizeSafeUrl(draft?.image_url, { allowRelative: true });
      if (safeImageUrl) {
        const link = document.createElement('a');
        link.className = 'draft-image-link';
        setSafeLink(link, safeImageUrl, { allowRelative: true });
        setText(link, 'Image attached');
        item.appendChild(link);
      }

      const actions = document.createElement('div');
      actions.className = 'draft-actions';
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.dataset.action = 'edit';
      editBtn.textContent = 'Edit';
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.dataset.action = 'delete';
      deleteBtn.textContent = 'Delete';
      const submitBtn = document.createElement('button');
      submitBtn.type = 'button';
      submitBtn.dataset.action = 'submit';
      submitBtn.textContent = 'Submit for moderation';
      actions.append(editBtn, deleteBtn, submitBtn);
      item.appendChild(actions);

      editBtn.addEventListener('click', () => openDraftEditor(els, state, draft));
      deleteBtn.addEventListener('click', async () => {
        try {
          await deleteDraft(draft.id);
          showToast('Черновик удалён.');
          await refreshDraftsList(els, state);
        } catch (error) {
          console.error('Ошибка удаления:', error);
          handlePossiblyUnauthorized(error, state, els);
          showToast(error.message || 'Не удалось удалить черновик.');
        }
      });
      submitBtn.addEventListener('click', async () => {
        try {
          await submitForModeration(draft.id);
          showToast('Черновик отправлен на модерацию.');
          await refreshDraftsList(els, state);
        } catch (error) {
          console.error('Ошибка отправки на модерацию:', error);
          handlePossiblyUnauthorized(error, state, els);
          showToast(error.message || 'Не удалось отправить на модерацию.');
        }
      });

      els.draftsList.appendChild(item);
    });
  } catch (error) {
    console.error('Ошибка загрузки черновиков:', error);
    handlePossiblyUnauthorized(error, state, els);
    showToast(error.message || 'Не удалось загрузить черновики.');
  } finally {
    state.isRefreshingDrafts = false;
  }
}

function openDraftEditor(els, state, draft) {
  state.activeDraftId = draft?.id || null;
  els.draftForm.reset();
  renderFieldErrors(els.draftForm, els.draftErrors, {});

  if (draft) {
    for (const [key, value] of Object.entries(draft)) {
      if (els.draftForm[key] && value !== null && value !== undefined) {
        els.draftForm[key].value = Array.isArray(value) ? value.join(', ') : value;
      }
    }
    if (Array.isArray(draft.coords)) {
      els.draftForm.longitude.value = draft.coords[0] ?? '';
      els.draftForm.latitude.value = draft.coords[1] ?? '';
    }
  }

  openModal(els.draftModal);
}

function collectDraftPayload(form) {
  const sourceMediaUrl = form.source_media_url.value.trim();
  return {
    name_ru: form.name_ru.value.trim(),
    name_en: form.name_en.value.trim(),
    layer_id: form.layer_id.value,
    date_start: form.date_start.value,
    date_construction_end: form.date_construction_end.value,
    date_end: form.date_end.value,
    longitude: form.longitude.value,
    latitude: form.latitude.value,
    influence_radius_km: form.influence_radius_km.value,
    title_short: form.title_short.value.trim(),
    description: form.description.value.trim(),
    tags: form.tags.value,
    source_media_url: sourceMediaUrl,
    source_url: form.source_url ? form.source_url.value.trim() : sourceMediaUrl,
    image_url: form.image_url ? form.image_url.value.trim() : sourceMediaUrl,
    coordinates_source: form.coordinates_source ? form.coordinates_source.value.trim() : '',
    source_license: form.source_license.value.trim()
  };
}

// Показывает ошибки рядом с соответствующими полями формы.
function renderFieldErrors(form, container, errors) {
  container.replaceChildren();
  form.querySelectorAll('.field-error-message').forEach((node) => node.remove());
  form.querySelectorAll('.is-invalid').forEach((node) => node.classList.remove('is-invalid'));

  Object.entries(errors).forEach(([field, message]) => {
    const normalizedMessage = VALIDATION_ERROR_MESSAGES[String(message || '').trim()] || toSafeText(message);
    const row = document.createElement('div');
    row.className = 'field-error';
    setText(row, `${toSafeText(field)}: ${toSafeText(normalizedMessage)}`);
    container.appendChild(row);

    const input = form[field];
    if (!input) return;
    input.classList.add('is-invalid');
    const inline = document.createElement('div');
    inline.className = 'field-error-message';
    setText(inline, normalizedMessage);
    input.insertAdjacentElement('afterend', inline);
  });
}

function hydrateLayerSelect(layers) {
  const select = document.querySelector('#draft-form select[name="layer_id"]');
  if (!select) return;
  const known = new Set([...select.options].map((option) => option.value));
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const id = String(layer?.id || '').trim();
    if (!id || known.has(id)) return;
    known.add(id);
    select.appendChild(new Option(toSafeText(layer.name_ru, id), id));
  });
}

function syncAuthUI(els) {
  const loggedIn = Boolean(getCurrentUser());
  els.authButtons.hidden = loggedIn;
  els.profilePanel.hidden = !loggedIn;
}

function bindModalClosers(els) {
  [els.loginModal, els.draftModal].forEach((modal) => {
    modal.addEventListener('click', (event) => {
      const closeBtn = event.target.closest?.('[data-close-modal]');
      if (event.target === modal || closeBtn) {
        closeModal(modal);
      }
    });
  });
}

function openModal(node) {
  if (!node || !node.hidden) return;
  node.hidden = false;
  document.body.classList.add('modal-open');
}

function closeModal(node) {
  if (!node || node.hidden) return;
  node.hidden = true;
  const hasVisibleModal = [...document.querySelectorAll('.modal')].some((modal) => !modal.hidden);
  if (!hasVisibleModal) document.body.classList.remove('modal-open');
}

function setLoading(form, loading) {
  form.querySelectorAll('button, input, select, textarea').forEach((node) => {
    if (node.type === 'file') {
      node.disabled = loading;
      return;
    }
    if (node.tagName === 'BUTTON') node.disabled = loading;
  });
}

function humanStatus(status) {
  if (status === 'pending') return 'Ожидает модерации';
  if (status === 'approved') return 'Одобрено';
  if (status === 'rejected') return 'Отклонено';
  return 'Черновик';
}

function showToast(message) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
  }
  setText(toast, message);
  toast.classList.add('show');
  window.clearTimeout(showToast.timerId);
  showToast.timerId = window.setTimeout(() => toast.classList.remove('show'), 2800);
}

function handlePossiblyUnauthorized(error, state, els) {
  if (error?.type === 'auth' || String(error?.message || '').includes('Требуется повторный вход')) {
    state.pendingAfterLogin = 'open-editor';
    openModal(els.loginModal);
  }
}
